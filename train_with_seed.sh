#!/bin/bash
#SBATCH --nodes=1
#SBATCH --time=07:59:00
#SBATCH --job-name=seeds_train
#SBATCH --mem=8GB
#SBATCH --ntasks=8
#SBATCH --gres=gpu:1 
#SBATCH --partition=ce-mri

seed=$1
nvidia-smi
model_dir=/scratch/sultan.a/AAAI2021-PDD/model_$seed

sleep 10;
echo Training with $seed
# python train_adp.py --model ensemble_3_resnet18 --seed $seed --model-basepath $model_dir --dataset CIFAR100 --bs 64 --lr 0.02 --alpha 2.0 --lamda 0.5 --save_dir bs

exit;
