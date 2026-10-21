"""Offline base/adapter generation on held-out questions. Never executes selected tools."""

import argparse, json
from pathlib import Path
from warehouse_agents.finetune.train import SYSTEM, load_dataset


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--revision', required=True)
    p.add_argument('--adapter')
    p.add_argument('--output', required=True)
    a = p.parse_args()
    rows = [r for r in load_dataset(a.data) if r['split'] == 'test']
    if len({r['scenario_id'] for r in rows}) != len(rows):
        raise ValueError('Test scenario IDs must be unique')
    output = Path(a.output)
    if output.exists():
        raise SystemExit('Output exists; use a new file')
    from transformers import AutoTokenizer, AutoModelForCausalLM
    import torch

    tokenizer = AutoTokenizer.from_pretrained(a.model, revision=a.revision, trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(
        a.model, revision=a.revision, trust_remote_code=False, dtype=torch.float32
    )
    if a.adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, a.adapter)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model.to(device)
    model.eval()
    predictions = {}
    with torch.inference_mode():
        for r in rows:
            prompt = tokenizer.apply_chat_template(
                [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': r['question']}],
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            inputs = tokenizer(prompt, return_tensors='pt').to(device)
            result = model.generate(
                **inputs, max_new_tokens=160, do_sample=False, pad_token_id=tokenizer.eos_token_id
            )
            predictions[r['scenario_id']] = tokenizer.decode(
                result[0, inputs['input_ids'].shape[1] :], skip_special_tokens=True
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(predictions, indent=2))


if __name__ == '__main__':
    main()
