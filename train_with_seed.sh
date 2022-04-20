#!/bin/bash
#SBATCH --nodes=1
#SBATCH --time=07:59:00
#SBATCH --job-name=seeds_train
#SBATCH --mem=32GB
#SBATCH --ntasks=16
#SBATCH --gres=gpu:1
#SBATCH --output=./slurm_reports/train_seeds.%j.out
#SBATCH --error=./slurm_reports/train_seeds.%j.err
#SBATCH --partition=gpu

nvidia-smi
model_dir=/scratch/sultan.a/adp_models_reproduce

which python

seed=$1

echo Training with $seed
python train_cifar.py --load_from_checkpoint=True --model_dir=$model_dir --seed=$seed --lamda=2 --log_det_lamda=0.5 --num_models=3 --augmentation=True --dataset=cifar10

exit;
