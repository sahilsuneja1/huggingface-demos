from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from datasets import load_dataset
import time
import torch
from tqdm import tqdm
from multiprocessing import Process, Queue

from custom_gen_class import modify_generation

TORCH_DEVICE = 0
TORCH_DTYPE = torch.bfloat16
LOAD_IN_8BIT = False
GEN_LEN = 128
NUM_SAMPLES = 5
MODEL_NAME = "google/flan-ul2"
AUX_MODEL = "google/flan-t5-small"
DBG = False


def run_prediction_loop(model, tokenizer):
    outputs = []
    gen_time = []
    num_tokens = []
    ds = load_dataset("cnn_dailymail", "3.0.0", split="validation", streaming=True)
    ds_iterator = iter(ds.take(NUM_SAMPLES))

    desc = "OG model" if not hasattr(model, "fwd_tokens") else f"NEW model ({model.fwd_tokens} tokens forwarded)"
    pbar = tqdm(range(NUM_SAMPLES), desc)
    for _ in pbar:
        next_data = "Summarize: " + next(ds_iterator)["article"]
        inputs = tokenizer([next_data], return_tensors="pt")
        inputs = inputs.to(TORCH_DEVICE)

        start = time.time()
        gen_out = model.generate(**inputs, do_sample=False, max_new_tokens=GEN_LEN)
        end = time.time()

        outputs.append(tokenizer.decode(gen_out[0]))
        gen_time.append(end - start)
        num_tokens.append(gen_out.shape[1])

        if hasattr(model, "fwd_tokens"):
            pbar.set_description(f"NEW model ({model.fwd_tokens} tokens forwarded)")

    print(f"OG Average time per input (ms): {(sum(gen_time) / len(gen_time))*1000:.2f}")
    print(f"OG Average time per token (ms): {(sum(gen_time) / sum(num_tokens))*1000:.2f}")
    return outputs


def run_og_model(queue):
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSeq2SeqLM.from_pretrained(
        MODEL_NAME,
        device_map="auto",
        max_memory={0: "18GiB", "cpu": "50GiB"},
        torch_dtype=TORCH_DTYPE,
        load_in_8bit=LOAD_IN_8BIT,
    )
    og_outputs = run_prediction_loop(model, tokenizer)
    queue.put(og_outputs)


def run_new_model(queue):
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

    aux_model = AutoModelForSeq2SeqLM.from_pretrained(AUX_MODEL)
    aux_model = aux_model.to(TORCH_DEVICE)

    model = AutoModelForSeq2SeqLM.from_pretrained(
        MODEL_NAME,
        device_map="auto",
        max_memory={0: "18GiB", "cpu": "50GiB"},
        torch_dtype=TORCH_DTYPE,
        load_in_8bit=LOAD_IN_8BIT,
    )
    model = modify_generation(model, aux_model)
    new_outputs = run_prediction_loop(model, tokenizer)
    queue.put(new_outputs)


def get_mismatches(og_outputs, new_outputs):
    mismatches = 0
    for i in range(NUM_SAMPLES):
        if og_outputs[i] != new_outputs[i]:
            mismatches += 1
            if TORCH_DTYPE is None:  # float 16 is a bit unstable, float 32 gets the same results
                print("\nOG :", og_outputs[i])
                print("NEW:", new_outputs[i])
    print(f"Mismatches: {mismatches}")


if __name__ == "__main__":
    queue = Queue()

    if DBG:
        run_new_model(queue)
        exit()

    p = Process(target=run_og_model, args=(queue,))
    p.start()
    p.join()  # this blocks until the process terminates
    og_outputs = queue.get()

    p = Process(target=run_new_model, args=(queue,))
    p.start()
    p.join()  # this blocks until the process terminates
    new_outputs = queue.get()

    get_mismatches(og_outputs, new_outputs)