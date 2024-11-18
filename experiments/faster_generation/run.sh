#model_checkpoint="meta-llama/Meta-Llama-3-70B-Instruct"
model_checkpoint="meta-llama/Meta-Llama-3-8B-Instruct"
assistant_checkpoint="meta-llama/Llama-3.2-1B"

python benchmark_decoder_open.py \
    $model_checkpoint \
    --aux-model $assistant_checkpoint \
    --dtype fp16 \
    --num-samples 3 \
    --max-gpu-memory 60 60 60 60 

