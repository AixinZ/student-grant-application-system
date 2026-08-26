const dataGeneratorForm = document.querySelector("#data-generator-form");
const errorSummary = document.querySelector("#error-summary");

if (errorSummary) {
  errorSummary.focus();
}

if (dataGeneratorForm) {
  dataGeneratorForm.addEventListener("submit", () => {
    if (!dataGeneratorForm.checkValidity()) {
      return;
    }
    const button = dataGeneratorForm.querySelector('button[type="submit"]');
    if (button) {
      button.disabled = true;
      button.textContent = "Generating…";
    }
  });
}
