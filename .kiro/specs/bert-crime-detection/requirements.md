# Requirements Document

## Introduction

This feature replaces the current rule-based keyword matching system in CyberGuard with a BERT-based machine learning pipeline for cybercrime classification. The pipeline covers the full ML lifecycle: data ingestion from the existing `dataset.csv` (HDFS-compatible), preprocessing, tokenization, model training, inference, and result visualization. The trained model is integrated into the Flask web app so that complaint descriptions and the `/analyze` endpoint use BERT predictions instead of (or alongside) keyword rules. The system must remain deployable on Railway with a PostgreSQL (Supabase) backend.

---

## Glossary

- **BERT_Model**: The fine-tuned `bert-base-uncased` transformer model used for cybercrime text classification.
- **Pipeline**: The end-to-end sequence of steps: data collection → preprocessing → tokenization → training → inference → visualization.
- **Dataset**: The CSV file (`dataset.csv`) containing labeled cybercrime text samples with `text` and `category` columns.
- **Tokenizer**: The Hugging Face `BertTokenizer` that converts raw text into token IDs and attention masks.
- **Preprocessor**: The component responsible for cleaning, normalizing, and splitting the Dataset into train/validation/test sets.
- **Trainer**: The component that fine-tunes the BERT_Model on the preprocessed Dataset.
- **Inference_Engine**: The component that loads the trained BERT_Model and produces crime category predictions for new text inputs.
- **Confidence_Score**: A float in [0.0, 1.0] representing the model's softmax probability for the predicted class.
- **Crime_Category**: One of the discrete labels present in the Dataset (e.g., `phishing`, `hacking`, `fraud`, `cyberbullying`).
- **Visualization_Module**: The component that generates training metrics charts and prediction distribution plots.
- **Model_Artifact**: The saved BERT_Model weights and Tokenizer files persisted to disk after training.
- **Fallback_Classifier**: The existing rule-based keyword matching logic in `app.py` used when the BERT_Model is unavailable.
- **Admin_Dashboard**: The existing `/dashboard` route in the Flask app, accessible only to admin users.
- **CyberGuard**: The Flask web application being extended with this feature.

---

## Requirements

### Requirement 1: Data Collection and Ingestion

**User Story:** As a data engineer, I want to load the cybercrime dataset from a CSV file (HDFS-compatible path), so that the Pipeline has a consistent, reproducible data source.

#### Acceptance Criteria

1. THE Pipeline SHALL load the Dataset from a configurable file path (defaulting to `dataset.csv` in the project root).
2. WHEN the Dataset file is not found at the configured path, THE Pipeline SHALL raise a descriptive `FileNotFoundError` and halt execution.
3. WHEN the Dataset file is missing the required `text` or `category` columns, THE Pipeline SHALL raise a descriptive `ValueError` identifying the missing columns.
4. THE Pipeline SHALL support CSV files encoded in UTF-8.
5. WHEN the Dataset contains duplicate rows (identical `text` and `category`), THE Preprocessor SHALL remove duplicates before any further processing.

---

### Requirement 2: Data Preprocessing

**User Story:** As a data scientist, I want the raw text data cleaned and normalized before tokenization, so that the BERT_Model trains on consistent, high-quality input.

#### Acceptance Criteria

1. THE Preprocessor SHALL convert all input text to lowercase before tokenization.
2. THE Preprocessor SHALL remove leading and trailing whitespace from each text sample.
3. THE Preprocessor SHALL remove HTML tags and URLs from text samples using regex substitution.
4. THE Preprocessor SHALL encode Crime_Category labels as integer indices using a consistent label mapping that is saved alongside the Model_Artifact.
5. THE Preprocessor SHALL split the Dataset into train, validation, and test sets using a configurable ratio (default: 70% train, 15% validation, 15% test) with a fixed random seed for reproducibility.
6. WHEN the Dataset contains fewer than 10 samples after deduplication, THE Preprocessor SHALL raise a `ValueError` stating the dataset is too small to split.

---

### Requirement 3: Tokenization

**User Story:** As a data scientist, I want text samples tokenized using the BERT tokenizer, so that the BERT_Model receives properly formatted input tensors.

#### Acceptance Criteria

1. THE Tokenizer SHALL use the `bert-base-uncased` pretrained vocabulary.
2. THE Tokenizer SHALL truncate and pad all sequences to a configurable maximum length (default: 128 tokens).
3. THE Tokenizer SHALL produce `input_ids` and `attention_mask` tensors for each sample.
4. THE Tokenizer SHALL process samples in configurable batch sizes (default: 32) to manage memory usage.
5. WHEN a text sample exceeds the maximum token length, THE Tokenizer SHALL truncate the sequence and retain the first `max_length` tokens.

---

### Requirement 4: BERT Model Training

**User Story:** As a data scientist, I want to fine-tune a BERT model on the cybercrime dataset, so that the model learns to classify crime categories from complaint text.

#### Acceptance Criteria

1. THE Trainer SHALL initialize from the `bert-base-uncased` pretrained weights with a classification head sized to the number of unique Crime_Category labels in the Dataset.
2. THE Trainer SHALL train for a configurable number of epochs (default: 3) using the AdamW optimizer with a configurable learning rate (default: 2e-5).
3. WHEN each training epoch completes, THE Trainer SHALL compute and log training loss and validation accuracy.
4. THE Trainer SHALL save the best-performing Model_Artifact (highest validation accuracy) to a configurable output directory (default: `./model/`).
5. WHEN training completes, THE Trainer SHALL evaluate the BERT_Model on the held-out test set and log test accuracy and per-class F1 scores.
6. WHEN a CUDA-capable GPU is available, THE Trainer SHALL use it; otherwise THE Trainer SHALL fall back to CPU training.
7. IF available GPU memory is insufficient to hold the configured batch size, THEN THE Trainer SHALL reduce the batch size by half and log a warning before retrying.

---

### Requirement 5: Model Inference Integration

**User Story:** As a developer, I want the trained BERT model integrated into the Flask app's crime detection logic, so that complaint submissions and the analyze endpoint use ML-based classification.

#### Acceptance Criteria

1. THE Inference_Engine SHALL load the Model_Artifact from disk at application startup if the model directory exists.
2. WHEN the Model_Artifact is not present at startup, THE Inference_Engine SHALL log a warning and CyberGuard SHALL use the Fallback_Classifier for all predictions.
3. WHEN a complaint description is submitted via `/submit_complaint`, THE Inference_Engine SHALL classify the description and return the predicted Crime_Category and Confidence_Score.
4. WHEN the Confidence_Score for the top prediction is below 0.60, THE Inference_Engine SHALL also return the Fallback_Classifier result alongside the BERT prediction.
5. THE Inference_Engine SHALL return a prediction within 2 seconds for a single text input of up to 512 characters on the deployed Railway environment.
6. WHEN the Inference_Engine raises an unhandled exception during prediction, THE CyberGuard SHALL catch the exception, log it, and use the Fallback_Classifier result so that complaint submission is not interrupted.
7. THE Inference_Engine SHALL log each prediction (input text, predicted Crime_Category, Confidence_Score, and source `bert`) to the `ai_analysis_logs` table.

---

### Requirement 6: Training Visualization

**User Story:** As a data scientist, I want training metrics and prediction distributions visualized, so that I can evaluate model performance and diagnose training issues.

#### Acceptance Criteria

1. THE Visualization_Module SHALL generate a line chart of training loss per epoch and save it as a PNG file to the configured output directory.
2. THE Visualization_Module SHALL generate a line chart of validation accuracy per epoch and save it as a PNG file to the configured output directory.
3. THE Visualization_Module SHALL generate a confusion matrix heatmap from test set predictions and save it as a PNG file to the configured output directory.
4. THE Visualization_Module SHALL generate a bar chart showing the distribution of Crime_Category labels in the Dataset and save it as a PNG file to the configured output directory.
5. WHEN the output directory does not exist, THE Visualization_Module SHALL create it before saving any files.
6. THE Visualization_Module SHALL operate without a display server (headless mode using the `Agg` matplotlib backend).

---

### Requirement 7: Admin Dashboard Integration

**User Story:** As an admin, I want to view BERT model performance metrics and prediction logs in the dashboard, so that I can monitor the model's effectiveness in production.

#### Acceptance Criteria

1. THE Admin_Dashboard SHALL display the current inference source (`bert` or `fallback`) for each entry in the `ai_analysis_logs` table.
2. THE Admin_Dashboard SHALL display the Confidence_Score alongside the predicted Crime_Category for BERT-sourced log entries.
3. WHEN the Model_Artifact is present on disk, THE Admin_Dashboard SHALL display the model's test accuracy and training date loaded from a metadata file saved alongside the Model_Artifact.
4. WHEN the Model_Artifact is absent, THE Admin_Dashboard SHALL display a notice indicating the BERT model has not been trained yet.

---

### Requirement 8: Pipeline Execution Script

**User Story:** As a developer, I want a single script to run the full training pipeline end-to-end, so that I can retrain the model with updated data without modifying application code.

#### Acceptance Criteria

1. THE Pipeline SHALL be executable as a standalone Python script (`train_pipeline.py`) from the project root.
2. WHEN executed, THE Pipeline SHALL run all phases in order: data loading → preprocessing → tokenization → training → evaluation → visualization.
3. THE Pipeline SHALL accept command-line arguments for `--data-path`, `--model-dir`, `--epochs`, `--lr`, `--max-len`, and `--batch-size`.
4. WHEN the Pipeline completes successfully, THE Pipeline SHALL print a summary including test accuracy, per-class F1 scores, and the path to saved Model_Artifact files.
5. IF any phase of the Pipeline raises an exception, THEN THE Pipeline SHALL log the error with a traceback and exit with a non-zero status code.

---

### Requirement 9: Dataset Round-Trip Integrity

**User Story:** As a data engineer, I want to verify that label encoding and decoding are lossless, so that predictions can always be mapped back to human-readable Crime_Category names.

#### Acceptance Criteria

1. THE Preprocessor SHALL save the label-to-index mapping as a JSON file alongside the Model_Artifact.
2. THE Inference_Engine SHALL load the label mapping from the JSON file at startup.
3. FOR ALL Crime_Category labels present in the Dataset, encoding a label to an index and decoding the index back to a label SHALL produce the original label (round-trip property).
4. WHEN the label mapping file is missing at inference time, THE Inference_Engine SHALL raise a descriptive `FileNotFoundError` and fall back to the Fallback_Classifier.
