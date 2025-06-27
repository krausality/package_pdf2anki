# Frequently Asked Questions (FAQ)

## Q: I'm using the default preset with `-d` flag, but I want to change only the model to `google/gemini-2.5-flash-preview` for everything. Is there a way to do this without typing long CLI commands?

**Current command output:**
```terminal
pdf2anki pdf2text . -d
[INFO] Batch mode activated. Found 3 PDF(s) in '.'.
[INFO] Applying preset default OCR settings (-d flag used).
[INFO] Using preset for --model: ['google/gemini-2.0-flash-001']
[INFO] Using preset for --repeat: [2]
[INFO] Using preset for --judge-model: google/gemini-2.0-flash-001
[INFO] Using preset for --judge-mode: authoritative
[INFO] Using preset for --judge-with-image: True
[INFO] Detected 16 CPU cores. Using up to 3 parallel worker processes.
```

**A:** Yes, there are several ways to keep the defaults but only change the model:

### Option 1: Change Default Model Configuration (Recommended)

Change the `default_model` in the configuration:

```bash
pdf2anki config set default_model google/gemini-2.5-flash-preview
pdf2anki pdf2text . -d
```

This changes both the OCR model and the judge model to the new model, since both normally fall back to `default_model`.

### Option 2: Update Preset Defaults for All Models

If you want to permanently set the defaults to the new model:

```bash
pdf2anki config set defaults model google/gemini-2.5-flash-preview
pdf2anki config set defaults judge_model google/gemini-2.5-flash-preview
pdf2anki pdf2text . -d
```

### Option 3: Command-Line Override (Short)

You can override just the `--model` and keep the rest of the defaults:

```bash
pdf2anki pdf2text . -d --model google/gemini-2.5-flash-preview
```

This keeps `--repeat 2`, `--judge-mode authoritative`, and `--judge-with-image` from the defaults, but overrides the model.

**Recommendation:** Option 1 is probably most practical - change the `default_model` once and then simply use `-d`. The `default_model` is automatically used as the judge model when no specific judge model is configured.

---

## Q: What happens to the judge model with Option 3?

**A:** With Option 3, the following happens:

```bash
pdf2anki pdf2text . -d --model google/gemini-2.5-flash-preview
```

The `--model` flag overrides **only** the OCR model, but **not** the judge model. This means:

- **OCR Model**: `google/gemini-2.5-flash-preview` (overridden)
- **Judge Model**: `google/gemini-2.0-flash-001` (remains at default from `-d`)

You would have **mixed models** - the new model for OCR, but the old one for judging.

If you want the new model for **both**, you would need to explicitly set the judge model too:

```bash
pdf2anki pdf2text . -d --model google/gemini-2.5-flash-preview --judge-model google/gemini-2.5-flash-preview
```

But this becomes long again.

**That's why Option 1 is better:**
```bash
pdf2anki config set default_model google/gemini-2.5-flash-preview
pdf2anki pdf2text . -d
```

Then **both** (OCR and Judge) automatically use the new model, and you can continue using just `-d`.