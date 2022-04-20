#!/bin/bash

# pyenv shell PD

function train_seeds()
{
    seeds=(8388 1759 5933 7916 7445 6130 7422 4066 3098 5469 4456 2302 9062 2724 8420);
    echo launching job with seed ${seeds[0]};
    last_job_id=$(sbatch --dependency=afterany: train_with_seed.sh $seed);

    for seed in ${seeds[@]:1}; do
        echo launching job with seed $seed
	    $(sbatch --dependency=afterany:$last_job_id train_with_seed.sh $seed)
    done
}

train_seeds;

exit;
 
