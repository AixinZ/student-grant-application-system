// Coordinates the CSV scoring page with the server-side scoring API.

(() => {
  const form = document.querySelector("#csv-scoring-form");
  if (!form) return;

  const fileInput = document.querySelector("#csv-scoring-file");
  const dropZone = document.querySelector("#csv-scoring-drop-zone");
  const fields = document.querySelector("#csv-scoring-fields");
  const fieldOptions = document.querySelector("#csv-scoring-field-options");
  const model = document.querySelector("#csv-scoring-model");
  const submit = document.querySelector("#csv-scoring-submit");
  const status = document.querySelector("#csv-scoring-status");
  const download = document.querySelector("#csv-scoring-download");
  const error = document.querySelector("#csv-scoring-error");
  const csrfToken = document.querySelector("#csv-scoring-csrf");
  let uploadId = null;
  let pollTimer = null;
  let submitting = false;

  const errorMessages = {
    file_too_large: "The CSV file is too large.",
    invalid_csv: "The file is not a valid CSV for scoring.",
    invalid_job: "Choose at least one output column and an available model.",
    invalid_request: "Your session could not be verified. Refresh the page and try again.",
    missing_model_columns: "The selected model requires columns that are not in this CSV.",
    model_unavailable: "The selected model is unavailable.",
    not_found: "The upload or scoring task is no longer available.",
    processing_failed: "Scoring could not be completed. Try again with a new upload.",
    result_not_ready: "The scored file is not ready yet.",
  };

  function csrfHeaders() {
    return { "X-CSRFToken": csrfToken.value };
  }

  function clearError() {
    error.hidden = true;
    error.textContent = "";
  }

  function showError(code) {
    error.textContent = errorMessages[code] || "The scoring request could not be completed.";
    error.hidden = false;
    error.focus();
  }

  async function responseJson(response) {
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || "processing_failed");
    return body;
  }

  function selectedFields() {
    return Array.from(fieldOptions.querySelectorAll('input[type="checkbox"]:checked'))
      .map((input) => input.value);
  }

  function updateSubmitState() {
    submit.disabled = submitting || !uploadId || !model.value || selectedFields().length === 0;
  }

  function renderFields(headers) {
    fieldOptions.replaceChildren();
    headers.forEach((header, index) => {
      const id = `csv-scoring-field-${index}`;
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.id = id;
      checkbox.type = "checkbox";
      checkbox.value = header;
      checkbox.checked = true;
      checkbox.addEventListener("change", updateSubmitState);
      label.htmlFor = id;
      label.append(checkbox, ` ${header}`);
      fieldOptions.append(label, document.createElement("br"));
    });
    fields.disabled = false;
  }

  function stopPolling() {
    if (pollTimer) window.clearTimeout(pollTimer);
    pollTimer = null;
  }

  async function pollJob(jobId, attempts = 0) {
    try {
      const job = await fetch(`/csv-scoring/jobs/${encodeURIComponent(jobId)}`, { headers: csrfHeaders() })
        .then(responseJson);
      status.textContent = `Status: ${job.status}. Rows processed: ${job.progress_rows}.`;
      if (job.status === "completed") {
        download.href = `/csv-scoring/jobs/${encodeURIComponent(jobId)}/download`;
        download.hidden = false;
        submitting = false;
        updateSubmitState();
        return;
      }
      if (job.status === "failed") {
        showError(job.error || "processing_failed");
        submitting = false;
        updateSubmitState();
        return;
      }
      if (attempts >= 120) throw new Error("processing_failed");
      pollTimer = window.setTimeout(() => pollJob(jobId, attempts + 1), 1000);
    } catch (failure) {
      submitting = false;
      updateSubmitState();
      showError(failure.message);
    }
  }

  async function uploadFile(file) {
    if (!file) return;
    stopPolling();
    submitting = false;
    clearError();
    uploadId = null;
    download.hidden = true;
    fields.disabled = true;
    fieldOptions.replaceChildren();
    updateSubmitState();
    status.textContent = "Uploading CSV…";
    const data = new FormData();
    data.append("file", file);
    try {
      const upload = await fetch("/csv-scoring/uploads", {
        method: "POST",
        headers: csrfHeaders(),
        body: data,
      }).then(responseJson);
      uploadId = upload.upload_id;
      renderFields(upload.fields);
      status.textContent = `Uploaded ${upload.row_count} rows. Choose output columns and score the CSV.`;
    } catch (failure) {
      status.textContent = "Choose a CSV to begin.";
      showError(failure.message);
    }
    updateSubmitState();
  }

  fileInput.addEventListener("change", () => uploadFile(fileInput.files[0]));
  dropZone.addEventListener("dragover", (event) => event.preventDefault());
  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    uploadFile(event.dataTransfer.files[0]);
  });
  dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });
  dropZone.addEventListener("click", () => fileInput.click());
  model.addEventListener("change", updateSubmitState);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitting || selectedFields().length === 0) {
      showError("invalid_job");
      return;
    }
    submitting = true;
    clearError();
    download.hidden = true;
    status.textContent = "Starting scoring task…";
    updateSubmitState();
    try {
      const job = await fetch("/csv-scoring/jobs", {
        method: "POST",
        headers: { ...csrfHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ upload_id: uploadId, selected_fields: selectedFields(), model_id: model.value }),
      }).then(responseJson);
      status.textContent = `Status: ${job.status}. Rows processed: ${job.progress_rows}.`;
      pollJob(job.job_id);
    } catch (failure) {
      submitting = false;
      updateSubmitState();
      showError(failure.message);
    }
  });
})();
