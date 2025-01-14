import torch
import torch.nn as nn
import torch.optim as optim
import argparse
import os
from pathlib import Path

from torch.autograd import Variable
from networks.ensemble_resnet import ensemble_3_resnet18, ensemble_5_resnet18, ensemble_3_resnet34, ensemble_5_resnet34
from config.dataset_config import getData

from datetime import datetime
from timeit import default_timer as timer

import numpy as np
import random


parser = argparse.ArgumentParser(description='PyTorch CNN Training')
parser.add_argument(
    '--model',
    type=str,
    default='ensemble_3_resnet18',
    help='CNN architecture')
parser.add_argument('--dataset', type=str, default='CIFAR100', help='datasets')
parser.add_argument('--use-progressbar', type=bool,
                    default=True, help='Use Progressbar to track training/testing progress')
parser.add_argument('--seed', type=int, default=1234, help='seed')
parser.add_argument('--bs', default=64, type=int, help='batch size')
parser.add_argument('--lr', default=0.02, type=float, help='learning rate')
parser.add_argument('--alpha', default=2.0, type=float, help='alpha')
parser.add_argument('--lamda', default=0.5, type=float, help='lamda')
parser.add_argument('--model-basepath', type=str,
                    default='./models', help='basepath of model directory')
parser.add_argument(
    '--resume',
    '-r',
    action='store_true',
    help='resume from checkpoint')
parser.add_argument(
    '--save_dir',
    type=str,
    default='adp',
    help='save log and model')
parser.add_argument('--no-progressbar', action='store_true')
parser.set_defaults(no_progressbar=False)
opt = parser.parse_args()

if not opt.no_progressbar:
    import progress

torch.manual_seed(opt.seed)
random.seed(opt.seed)
np.random.seed(opt.seed)

# assert opt.model == opt.save_dir

use_cuda = torch.cuda.is_available()

print('use_cuda:', use_cuda)

best_Test_acc = 0  # best PublicTest accuracy
best_Test_acc_epoch = 0
start_epoch = 0  # start from epoch 0 or last checkpoint epoch

if opt.dataset == 'FashionMNIST':
    total_epoch = 40
if opt.dataset == 'CIFAR100':
    total_epoch = 200
if opt.dataset == 'Tiny_Image':
    total_epoch = 100

path = os.path.join(opt.model_basepath, opt.dataset,
                    opt.save_dir+'_'+opt.model)
Path(path).mkdir(parents=True, exist_ok=True)

results_log_csv_name = opt.save_dir + '_results.csv'

print('==> Preparing data..')

# setup data loader
num_classes, train_data, test_data = getData(opt.dataset)
trainloader = torch.utils.data.DataLoader(
    train_data,
    batch_size=opt.bs,
    shuffle=True,
    num_workers=8,
    pin_memory=True)
testloader = torch.utils.data.DataLoader(
    test_data,
    batch_size=64,
    shuffle=False,
    num_workers=4,
    pin_memory=True)

# Model
if opt.model == 'ensemble_3_resnet18':
    num_models = 3
    net = ensemble_3_resnet18(num_classes, num_models)
elif opt.model == 'ensemble_5_resnet18':
    num_models = 5
    net = ensemble_5_resnet18(num_classes, num_models)
elif opt.model == 'ensemble_3_resnet34':
    num_models = 3
    net = ensemble_3_resnet34(num_classes, num_models)
elif opt.model == 'ensemble_5_resnet34':
    num_models = 5
    net = ensemble_5_resnet34(num_classes, num_models)
else:
    raise NotImplementedError

# setup optimizer
optimizer = optim.SGD(
    net.parameters(),
    lr=opt.lr,
    momentum=0.9,
    weight_decay=5e-4)

scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
    optimizer, T_max=total_epoch, eta_min=1e-4)

# setup checkpoint
if opt.resume:
    # Load checkpoint.
    print('==> Resuming from checkpoint..')
    assert os.path.isdir(path), 'Error: no checkpoint directory found!'
    checkpoint = torch.load(os.path.join(path, 'best_model.pth'))

    net.load_state_dict(checkpoint['net'])
    best_Test_acc = checkpoint['acc']
    best_Test_acc_epoch = checkpoint['epoch']
    start_epoch = checkpoint['epoch'] + 1
    for x in range(start_epoch):
        # optimizer.step()
        scheduler.step()
else:
    print('==> Preparing %s %s' % (opt.model, opt.dataset))
    print('==> Building model..')

# covert net to GPU
if use_cuda:
    net = net.cuda()


class LogNLLLoss(nn.Module):

    def __init__(self, reduction='mean'):
        super(LogNLLLoss, self).__init__()
        assert reduction == 'mean'
        self.reduction = reduction

    def forward(self, x, targets):
        log_x = torch.log(x)
        log_nll_loss = nn.NLLLoss()(log_x, targets)
        return log_nll_loss


class LogDet(nn.Module):

    def __init__(self, num_models, num_classes, det_offset=1e-6):
        super(LogDet, self).__init__()
        self.num_models = num_models
        self.num_classes = num_classes
        self.det_offset = det_offset

    def forward(self, probs, targets):
        targets_one_hot = self.one_hot(targets, self.num_classes)
        conca_targets_one_hot = torch.cat(
            [targets_one_hot for n in range(self.num_models)], dim=-1)

        bool_R_mask = torch.BoolTensor(conca_targets_one_hot < 1)
        if torch.cuda.is_available():
            bool_R_mask = bool_R_mask.cuda()
        bool_R_targets = torch.masked_select(probs, bool_R_mask)

        mask_non_y_pred = bool_R_targets.view(
            [-1, self.num_models, self.num_classes - 1])
        mask_non_y_pred = mask_non_y_pred / \
            torch.norm(mask_non_y_pred, p=2, dim=2, keepdim=True)

        matrix = torch.matmul(
            mask_non_y_pred, mask_non_y_pred.permute(0, 2, 1))
        matrix_off = self.det_offset * \
            torch.unsqueeze(torch.eye(self.num_models).cuda(), 0) + matrix

        all_log_det = torch.logdet(matrix_off)
        return torch.mean(all_log_det)

    def one_hot(self, x, num_classes):
        y_one_hot = torch.eye(num_classes)[x, :]
        return y_one_hot


class ShannonEntropy(nn.Module):

    def __init__(self, num_models, num_classes, offset=1e-20):
        super(ShannonEntropy, self).__init__()
        self.num_models = num_models
        self.num_classes = num_classes
        self.offset = offset

    def forward(self, probs):
        y_probs_split = torch.split(probs, self.num_classes, dim=-1)
        y_p_all = 0
        for i in range(self.num_models):
            y_p_all += y_probs_split[i]
        SE = self.entropy(y_p_all / self.num_models)
        return torch.mean(SE)

    def entropy(self, y):
        return torch.sum(-torch.mul(y, torch.log(y + self.offset)), dim=-1)


class EnsembleCrossEntropy(nn.Module):

    def __init__(self, num_models, num_classes):
        super(EnsembleCrossEntropy, self).__init__()
        self.num_models = num_models
        self.num_classes = num_classes

    def forward(self, probs, target):
        assert probs.shape[-1] % self.num_models == 0
        criterion = LogNLLLoss()
        probs_split = torch.split(probs, self.num_classes, dim=-1)
        ce_loss_v = 0
        ce_loss_list = []
        for prob in probs_split:
            ce_loss_i = criterion(prob, target) / self.num_models
            ce_loss_list.append(ce_loss_i)
            ce_loss_v += ce_loss_i
        return ce_loss_v, ce_loss_list


def main():

    # record train log
    with open(os.path.join(path, results_log_csv_name), 'w') as f:
        f.write('epoch, train_loss, test_loss, train_ce_loss, train_se_loss, test_loged_loss, test_ce_loss, test_se_loss, test_loged_loss, train_acc, test_acc, time\n')

    # start train
    for epoch in range(start_epoch, total_epoch):
        print('current time:', datetime.now().strftime('%b%d-%H:%M:%S'))
        start = timer()
        train(epoch)
        end = timer()
        training_time = end-start
        start = timer()
        test(epoch)
        end = timer()
        test_time = end-start

        print(f'Epoch {epoch} training time: {training_time:.2f}')
        print(f'Epoch {epoch} test3 time: {test_time:.2f}')

        # Log results
        with open(os.path.join(path, results_log_csv_name), 'a') as f:
            f.write('%5d, %.5f, %.5f, %.5f, %.5f, %.5f, %.5f, %.5f, %.5f, %.6f, %.5f, %s,\n'
                    '' % (epoch,
                          train_loss,
                          Test_loss,
                          train_CE_loss,
                          train_SE_loss,
                          train_LogED_loss,
                          Test_CE_loss,
                          Test_SE_loss,
                          Test_LogED_loss,
                          Train_acc,
                          Test_acc,
                          datetime.now().strftime('%b%d-%H:%M:%S')))

    print("best_Test_acc: %.3f" % best_Test_acc)
    print("best_Test_acc_epoch: %d" % best_Test_acc_epoch)

    # best ACC
    with open(os.path.join(path, results_log_csv_name), 'a') as f:
        f.write('%s,%03d,%0.3f,\n' % ('best acc (test)',
                                      best_Test_acc_epoch,
                                      best_Test_acc))

# Training


def train(epoch):
    print('\nEpoch: %d' % epoch)
    global Train_acc
    global train_loss
    global train_CE_loss
    global train_SE_loss
    global train_LogED_loss
    net.train()
    train_loss = 0
    train_CE_loss = 0
    train_SE_loss = 0
    train_LogED_loss = 0
    correct = 0
    total = 0

    print('learning_rate: %s' % str(scheduler.get_last_lr()))
    for batch_idx, (inputs, targets) in enumerate(trainloader):

        if use_cuda:
            inputs, targets = inputs.cuda(), targets.cuda()
        inputs, targets = Variable(
            inputs, requires_grad=True), Variable(targets)
        outputs = net(inputs)

        CE_loss, CE_loss_list = EnsembleCrossEntropy(
            num_models, num_classes)(outputs, targets)
        SE_loss = ShannonEntropy(num_models, num_classes)(outputs)
        LogED_loss = LogDet(num_models, num_classes)(outputs, targets)
        loss = CE_loss - opt.alpha*SE_loss - opt.lamda*LogED_loss

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        scheduler.step()
        train_loss += loss.data
        train_CE_loss += CE_loss.data
        train_SE_loss += SE_loss.data
        train_LogED_loss += LogED_loss.data

        output_split = torch.split(outputs, num_classes, dim=-1)
        for out in output_split:
            _, p = torch.max(out.data, 1)
            correct += p.eq(targets.data).cpu().sum() / num_models
        total += targets.size(0)

        if not opt.no_progressbar:
            progress.progress_bar(
                batch_idx,
                len(trainloader),
                'Total_Loss: %.3f CE_Loss: %.3f SE_Loss: %.3f LogED_Loss: %.3f| Acc: %.3f%% (%d/%d)'
                '' % (train_loss / (batch_idx + 1),
                      train_CE_loss / (batch_idx + 1),
                      train_SE_loss / (batch_idx + 1),
                      train_LogED_loss / (batch_idx + 1),
                      100. * float(correct) / total,
                      correct,
                      total))
        else:
            if batch_idx % 50 == 0 or batch_idx == len(trainloader)-1:
                print('Epoch %d/%d Total_Loss: %.3f CE_Loss: %.3f SE_Loss: %.3f LogED_Loss: %.3f| Acc: %.3f%% (%d/%d)'
                      '' % (batch_idx, len(trainloader), train_loss / (batch_idx + 1),
                            train_CE_loss / (batch_idx + 1),
                            train_SE_loss / (batch_idx + 1),
                            train_LogED_loss / (batch_idx + 1),
                            100. * float(correct) / total,
                            correct,
                            total))

    Train_acc = 100. * float(correct) / total


def test(epoch):
    global Test_acc
    global best_Test_acc
    global best_Test_acc_epoch
    global Test_loss
    global Test_CE_loss
    global Test_SE_loss
    global Test_LogED_loss
    net.eval()
    Test_loss = 0
    Test_CE_loss = 0
    Test_SE_loss = 0
    Test_LogED_loss = 0
    correct = 0
    total = 0
    for batch_idx, (inputs, targets) in enumerate(testloader):
        if use_cuda:
            inputs, targets = inputs.cuda(), targets.cuda()
        inputs, targets = Variable(
            inputs, requires_grad=True), Variable(targets)
        outputs = net(inputs)

        CE_loss, CE_loss_list = EnsembleCrossEntropy(
            num_models, num_classes)(outputs, targets)
        SE_loss = ShannonEntropy(num_models, num_classes)(outputs)
        LogED_loss = LogDet(num_models, num_classes)(outputs, targets)
        loss = CE_loss - opt.alpha * SE_loss - opt.lamda * LogED_loss

        Test_loss += loss.data
        Test_CE_loss += CE_loss.data
        Test_SE_loss += SE_loss.data
        Test_LogED_loss += LogED_loss.data

        output_split = torch.split(outputs, num_classes, dim=-1)
        for out in output_split:
            _, p = torch.max(out.data, 1)
            correct += p.eq(targets.data).cpu().sum() / num_models
        total += targets.size(0)

        if not opt.no_progressbar:
            progress.progress_bar(
                batch_idx,
                len(testloader),
                'Total_Loss: %.3f CE_Loss: %.3f SE_Loss: %.3f LogED_Loss: %.3f | Acc: %.3f%% (%d/%d)'
                '' % (Test_loss / (batch_idx + 1),
                      Test_CE_loss/(batch_idx + 1),
                      Test_SE_loss / (batch_idx + 1),
                      Test_LogED_loss / (batch_idx + 1),
                      100. * float(correct)/total,
                      correct,
                      total))
        else:
            if batch_idx % 10 == 0 or batch_idx == len(testloader)-1:
                print(
                    'Epoch %d/%d Total_Loss: %.3f CE_Loss: %.3f SE_Loss: %.3f LogED_Loss: %.3f | Acc: %.3f%% (%d/%d)'
                    '' % (batch_idx, len(testloader), Test_loss / (batch_idx + 1),
                          Test_CE_loss/(batch_idx + 1),
                          Test_SE_loss / (batch_idx + 1),
                          Test_LogED_loss / (batch_idx + 1),
                          100. * float(correct)/total,
                          correct,
                          total)
                )
    # Save checkpoint.
    Test_acc = 100. * float(correct) / total
    if Test_acc > best_Test_acc:
        print('Saving..')
        print("best_Test_acc: %0.3f" % Test_acc)
        state = {
            'net': net.state_dict() if use_cuda else net,
            'acc': Test_acc,
            'epoch': epoch,
        }
        if not os.path.isdir(path):
            os.mkdir(path)
        torch.save(state, os.path.join(path, 'best_model.pth'))
        best_Test_acc = Test_acc
        best_Test_acc_epoch = epoch


if __name__ == '__main__':
    main()
