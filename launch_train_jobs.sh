#!/bin/bash

function train_seeds()
{
    seeds=(8388 1759 5933 7916 7445 6130 7422 4066 3098 5469 4456 2302 9062 2724 8420);
    # seeds=(6016 3844 7560 1289 4234 8844 7821 7322 8859 4510 2478 2735 6711 6073 3641 4416 9927 3152 5973 8406 3041 2533 6760 7532 7533 3950 3445 1910 5498 5884);    
    for seed in ${seeds[@]}; do
        echo launching job with seed $seed
	sbatch train_with_seed.sh $seed
    done
}

train_seeds;

exit;
 
