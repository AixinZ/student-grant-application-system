// Improves form feedback by focusing errors and preventing duplicate valid submissions.

const applicationForm = document.querySelector("#application-form");
const errorSummary = document.querySelector("#error-summary");

if (errorSummary) {
  errorSummary.focus();
}

if (applicationForm) {
  applicationForm.addEventListener("submit", () => {
    if (!applicationForm.checkValidity()) {
      return;
    }

    const submitButton = applicationForm.querySelector('button[type="submit"]');
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "Submitting…";
    }
  });
}
