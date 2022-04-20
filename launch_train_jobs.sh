#!/bin/bash

eval "$(pyenv init -)"

pyenv shell PD

REPORTS_PATH=slurm_reports/adp_train

function train_seeds()
{
    seeds=(8388 1759 5933 7916 7445 6130 7422 4066 3098 5469 4456 2302 9062 2724 8420);
    seed=${seeds[0]};
    rm -rf $REPORTS_PATH/seed_${seeds[0]};
    mkdir -p $REPORTS_PATH/seed_${seeds[0]};
    echo launching job with seed ${seeds[0]};
    last_job_id=$(sbatch --parsable --output=$REPORTS_PATH/seed_$seed/stdout --error=$REPORTS_PATH/seed_$seed/stderr train_with_seed.sh $seed);

    for seed in ${seeds[@]:1}; do
        echo launching job with seed $seed;
        rm -rf $REPORTS_PATH/seed_$seed;
        mkdir -p $REPORTS_PATH/seed_$seed;
	new_job_id=$(sbatch --parsable --output=$REPORTS_PATH/seed_$seed/stdout --error=$REPORTS_PATH/seed_$seed/stderr --dependency=afterany:$last_job_id train_with_seed.sh $seed);
        last_job_id=$new_job_id;
    done
}

train_seeds;

exit;
 
