// Improves form feedback by focusing errors and preventing duplicate valid submissions.

const applicationForm = document.querySelector("#application-form");
const errorSummary = document.querySelector("#error-summary");

if (errorSummary) {
  errorSummary.focus();
}

if (applicationForm) {
  /**
   * Prevent duplicate valid submissions while leaving invalid forms editable.
   *
   * @returns {void}
   *
   * The callback relies on native browser validation. Once the form is valid,
   * it disables the submit button and replaces its label with a progress state.
   */
  const handleApplicationSubmit = () => {
    if (!applicationForm.checkValidity()) {
      return;
    }

    const submitButton = applicationForm.querySelector('button[type="submit"]');
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "Submitting…";
    }
  };

  applicationForm.addEventListener("submit", handleApplicationSubmit);
}
