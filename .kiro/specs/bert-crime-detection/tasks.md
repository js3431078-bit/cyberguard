# Implementation Plan: BERT Crime Detection Pipeline

## Overview

Integrate a fine-tuned BERT model into CyberGuard to replace the rule-based keyword classifier. The plan covers the full ML lifecycle: data ingestion, preprocessing, tokenization, training, inference integration into Flask, visualization, and admin dashboard updates.

## Tasks

- [ ] 1. Set up project structure and dependencies
  - Add `transformers`, `torch`, `scikit-learn`, `matplotlib`, `seaborn`, `numpy`, `pandas` to `requirements.txt`
  - Create `bert_pipeline/` package directory with `__init__.py`
  - Create `model/` output directory (add to `.gitignore`)
  - _Requirements: 8.1, 8.2_

- [ ] 2. Implement data ingestion module
  - [ ] 2.1 Create `bert_pipeline/data_loader.py` with `load_dataset(path)` function
    - Load CSV from configurable path (default `dataset.csv`)
    - Validate presence of `text` and `category` columns; raise `ValueError` with missing column names if absent
    - Raise `FileNotFoundError` with descriptive message if file not found
    - Ensure UTF-8 encoding support
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [ ]* 2.2 Write unit tests for `load_dataset`
    - Test missing file raises `FileNotFoundError`
    - Test missing columns raises `ValueError`
    - Test valid CSV loads correctly
    - _Requirements: 1.2, 1.3_

- [ ] 3. Implement preprocessing module
  - [ ] 3.1 Create `bert_pipeline/preprocessor.py` with `Preprocessor` class
    - `clean_text(text)`: lowercase, strip whitespace, remove HTML tags and URLs via regex
    - `deduplicate(df)`: drop duplicate `(text, category)` rows
    - `encode_labels(df)`: build label-to-index mapping, save as `label_map.json` to model dir
    - `split(df, train_ratio, val_ratio, test_ratio, seed)`: stratified split with configurable ratios (default 70/15/15)
    - Raise `ValueError` if fewer than 10 samples after deduplication
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 9.1_
  - [ ]* 3.2 Write property test: label round-trip consistency
    - **Property: Round-trip encoding** — for all labels in dataset, `decode(encode(label)) == label`
    - **Validates: Requirements 9.3**
  - [ ]* 3.3 Write unit tests for `Preprocessor`
    - Test `clean_text` removes HTML, URLs, lowercases, strips whitespace
    - Test deduplication removes exact duplicate rows
    - Test `ValueError` raised when fewer than 10 samples
    - Test split ratios sum to 1.0 and produce correct proportions
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6_

- [ ] 4. Implement tokenization module
  - [ ] 4.1 Create `bert_pipeline/tokenizer.py` with `BertDataset` (PyTorch `Dataset`) and `tokenize_batch` helper
    - Use `bert-base-uncased` pretrained tokenizer
    - Truncate and pad to configurable `max_length` (default 128)
    - Produce `input_ids` and `attention_mask` tensors
    - Process in configurable batch sizes (default 32)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - [ ]* 4.2 Write unit tests for tokenizer
    - Test output contains `input_ids` and `attention_mask` keys
    - Test sequences longer than `max_length` are truncated to `max_length`
    - Test padding produces uniform tensor shapes within a batch
    - _Requirements: 3.2, 3.3, 3.5_

- [ ] 5. Implement BERT training module
  - [ ] 5.1 Create `bert_pipeline/trainer.py` with `Trainer` class
    - Initialize `BertForSequenceClassification` from `bert-base-uncased` with `num_labels` from dataset
    - Train for configurable epochs (default 3) with AdamW optimizer (default lr 2e-5)
    - Log training loss and validation accuracy after each epoch
    - Save best model (highest val accuracy) to configurable `model_dir` (default `./model/`)
    - Evaluate on test set after training; log test accuracy and per-class F1 scores
    - Auto-detect CUDA; fall back to CPU
    - Halve batch size and log warning if GPU OOM error occurs
    - Save `model_metadata.json` with test accuracy and training timestamp
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_
  - [ ]* 5.2 Write unit tests for `Trainer`
    - Test model initializes with correct number of output labels
    - Test metadata JSON is written after training completes
    - Test best model checkpoint is saved to `model_dir`
    - _Requirements: 4.1, 4.4, 4.5_

- [ ] 6. Checkpoint — Ensure pipeline modules are wired and tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implement visualization module
  - [ ] 7.1 Create `bert_pipeline/visualizer.py` with `Visualizer` class
    - Use `matplotlib` with `Agg` backend (headless, no display server)
    - `plot_loss(losses, output_dir)`: line chart of training loss per epoch → `training_loss.png`
    - `plot_accuracy(accuracies, output_dir)`: line chart of validation accuracy per epoch → `val_accuracy.png`
    - `plot_confusion_matrix(y_true, y_pred, labels, output_dir)`: seaborn heatmap → `confusion_matrix.png`
    - `plot_label_distribution(df, output_dir)`: bar chart of category counts → `label_distribution.png`
    - Create `output_dir` if it does not exist
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_
  - [ ]* 7.2 Write unit tests for `Visualizer`
    - Test each plot method creates the expected PNG file in the output directory
    - Test output directory is created when it does not exist
    - _Requirements: 6.5, 6.6_

- [ ] 8. Implement inference engine
  - [ ] 8.1 Create `bert_pipeline/inference.py` with `InferenceEngine` class
    - `load(model_dir)`: load model weights, tokenizer, and `label_map.json` at startup
    - Raise `FileNotFoundError` with descriptive message if `label_map.json` is missing; fall back to `Fallback_Classifier`
    - `predict(text)`: return `{"category": str, "confidence": float, "source": "bert"}`
    - If confidence < 0.60, also include `"fallback_result"` from rule-based classifier
    - Catch all unhandled exceptions; log and return fallback result so submission is never interrupted
    - Log each prediction to `ai_analysis_logs` table (input text, category, confidence, source `bert`)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6, 5.7, 9.2, 9.4_
  - [ ]* 8.2 Write property test: confidence score bounds
    - **Property: Confidence score is always in [0.0, 1.0]** for any non-empty input string
    - **Validates: Requirements 5.3**
  - [ ]* 8.3 Write unit tests for `InferenceEngine`
    - Test fallback is used when model directory is absent
    - Test missing `label_map.json` raises `FileNotFoundError` and triggers fallback
    - Test prediction returns `source: "bert"` when model is loaded
    - Test low-confidence prediction includes `fallback_result` key
    - _Requirements: 5.1, 5.2, 5.4, 9.4_

- [ ] 9. Create `train_pipeline.py` entry-point script
  - Wire all modules: `DataLoader → Preprocessor → Tokenizer → Trainer → Visualizer`
  - Accept CLI args: `--data-path`, `--model-dir`, `--epochs`, `--lr`, `--max-len`, `--batch-size`
  - Print summary on success: test accuracy, per-class F1, path to saved artifacts
  - Catch any phase exception; log with traceback and `sys.exit(1)`
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ] 10. Integrate `InferenceEngine` into `app.py`
  - [ ] 10.1 Load `InferenceEngine` at app startup (after `init_db()`)
    - If `./model/` exists, call `engine.load("./model/")`; otherwise log warning and set engine to `None`
    - _Requirements: 5.1, 5.2_
  - [ ] 10.2 Replace `detect_crime_type()` call in `/submit_complaint` with `InferenceEngine.predict()`
    - Use BERT prediction when engine is loaded; fall back to rule-based when engine is `None`
    - Store `confidence` and `source` in the complaint record or log
    - _Requirements: 5.3, 5.6_
  - [ ] 10.3 Replace `analyze_text()` call in `/analyze` endpoint with `InferenceEngine.predict()`
    - Return `confidence` and `source` fields in the JSON response
    - Fall back gracefully on exception
    - _Requirements: 5.3, 5.4, 5.6, 5.7_
  - [ ]* 10.4 Write integration tests for `/submit_complaint` and `/analyze` with mocked engine
    - Test BERT path returns correct category and confidence
    - Test fallback path is used when engine is `None`
    - _Requirements: 5.3, 5.6_

- [ ] 11. Update admin dashboard
  - [ ] 11.1 Update `/dashboard` route in `app.py` to pass model metadata to template
    - Load `model_metadata.json` if present; pass `model_accuracy`, `model_trained_at`, `model_available` to template
    - _Requirements: 7.3, 7.4_
  - [ ] 11.2 Update `templates/dashboard.html` to display BERT model status panel
    - Show test accuracy and training date when model is available
    - Show "BERT model not trained yet" notice when model is absent
    - Display `source` column (`bert` / `fallback`) and `confidence` in the AI analysis logs table
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [ ] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- `bert_pipeline/` is a local package; no separate install needed
- The `model/` directory is gitignored; run `train_pipeline.py` to populate it before starting the Flask app with BERT enabled
- Property tests validate universal correctness properties; unit tests cover specific examples and edge cases
