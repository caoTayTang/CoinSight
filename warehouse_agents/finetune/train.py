"""CUDA-only Unsloth experiment. Never imported by the serving runtime.

Input JSONL fields: split, scenario_id, question, target (intent/tool/arguments/needs_clarification).
External data must be reviewed; no generated dataset is presented as ground truth.
"""

import argparse
import hashlib
import json
from pathlib import Path

SYSTEM = (
    'Classify a CoinSight SRE request. Output only JSON with intent, tool, arguments, '
    'needs_clarification. Tools: service_health, warehouse_coverage, model_health, load_skill. '
    'Read-only. Never execute actions. Unknown or unsafe requests require clarification; tool=null.'
)
TOOLS = {'service_health', 'warehouse_coverage', 'model_health', 'load_skill'}


def load_dataset(path):
    records = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    groups = {}
    for r in records:
        if (
            r['split'] not in ('train', 'validation', 'test')
            or not r['scenario_id']
            or not r['question'].strip()
        ):
            raise ValueError('Missing or invalid split/scenario/question')
        if r['scenario_id'] in groups and groups[r['scenario_id']] != r['split']:
            raise ValueError('Scenario leakage across splits')
        groups[r['scenario_id']] = r['split']
        from jsonschema import validate
        from warehouse_agents.action_contracts import SCHEMAS

        target = r['target']
        if set(target) != {'intent', 'tool', 'arguments', 'needs_clarification'}:
            raise ValueError('Invalid target fields')
        if not isinstance(target['intent'], str) or not isinstance(target['needs_clarification'], bool):
            raise ValueError('Invalid target types')
        tool = target['tool']
        if tool is not None:
            if tool not in TOOLS:
                raise ValueError('Tool not allowed')
            validate(target['arguments'], SCHEMAS[tool])
        elif target['arguments'] != {} or not target['needs_clarification']:
            raise ValueError('Abstention requires clarification and no arguments')
    if any(not any(r['split'] == s for r in records) for s in ('train', 'validation', 'test')):
        raise ValueError('All three splits required')
    return records


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--model', default='unsloth/Qwen3-0.6B-unsloth-bnb-4bit')
    p.add_argument('--revision', required=True)
    p.add_argument('--validate-only', action='store_true')
    a = p.parse_args()
    records = load_dataset(a.data)
    counts = {s: sum(r['split'] == s for r in records) for s in ('train', 'validation', 'test')}
    if a.validate_only:
        print(json.dumps({'counts': counts, 'status': 'dataset_validation_only_not_trained'}))
        return
    import torch

    if not torch.cuda.is_available():
        raise SystemExit('CUDA GPU required. No training performed.')
    from unsloth import FastLanguageModel
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=a.model, revision=a.revision, max_seq_length=1024, load_in_4bit=True
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj'],
        lora_alpha=16,
        lora_dropout=0,
        bias='none',
        use_gradient_checkpointing='unsloth',
        random_state=42,
    )

    def dataset(split):
        texts = []
        for r in records:
            if r['split'] != split:
                continue
            messages = [
                {'role': 'system', 'content': SYSTEM},
                {'role': 'user', 'content': r['question']},
                {'role': 'assistant', 'content': json.dumps(r['target'], ensure_ascii=False)},
            ]
            texts.append(
                {
                    'text': tokenizer.apply_chat_template(
                        messages, tokenize=False, add_generation_prompt=False, enable_thinking=False
                    )
                }
            )
        return Dataset.from_list(texts)

    output = Path(a.output)
    if output.exists():
        raise SystemExit('Output exists; use a new experiment directory')
    config = SFTConfig(
        output_dir=str(output),
        dataset_text_field='text',
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        num_train_epochs=2,
        learning_rate=2e-4,
        seed=42,
        max_length=1024,
        logging_steps=1,
        eval_strategy='epoch',
        save_strategy='epoch',
        report_to='none',
    )
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        args=config,
        train_dataset=dataset('train'),
        eval_dataset=dataset('validation'),
    )
    trainer.train()
    trainer.save_model(str(output / 'adapter'))
    tokenizer.save_pretrained(str(output / 'adapter'))
    import subprocess

    manifest = dict(
        model=a.model,
        revision=a.revision,
        seed=42,
        counts=counts,
        data_sha256=hashlib.sha256(Path(a.data).read_bytes()).hexdigest(),
        environment=subprocess.check_output(['python', '-m', 'pip', 'freeze'], text=True),
        status='trained_not_promoted',
        limitations='Requires separate base versus adapter held-out evaluation. No deployment implied.',
    )
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
