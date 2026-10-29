const form = document.getElementById("contactForm");
const submitBtn = document.getElementById("submitBtn");
const errorPopup = document.getElementById("errorPopup");
const errorMessage = document.getElementById("errorMessage");
let fieldToFocusAfterError = null;

// Defensive cleanup: ensure no legacy popup dialog exists in the DOM
const legacySuccessPopup = document.getElementById("successPopup");
if (legacySuccessPopup) legacySuccessPopup.remove();
document.querySelectorAll(".popup-overlay:not(.alert-overlay)").forEach((el) => el.remove());

function hideErrorPopup() {
  if (errorPopup) errorPopup.hidden = true;
  if (fieldToFocusAfterError) fieldToFocusAfterError.focus();
}
const errorRetryBtn = document.getElementById("errorRetry");
if (errorRetryBtn) errorRetryBtn.addEventListener("click", hideErrorPopup);
if (errorPopup) {
  errorPopup.addEventListener("click", (e) => { if (e.target === errorPopup) hideErrorPopup(); });
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && errorPopup && !errorPopup.hidden) {
    hideErrorPopup();
  }
});

// Ensure WhatsApp checkbox is always unchecked by default
function resetOptInCheckbox() {
  const optIn = document.getElementById("whatsapp_opt_in");
  if (optIn) optIn.checked = false;
}
resetOptInCheckbox();
window.addEventListener("pageshow", resetOptInCheckbox);

function fieldLabel(fieldName) {
  const labels = {
    full_name: "Full name", FirstName: "First Name", "Last Name": "Last Name",
    email: "Email", Email: "Email",
    contact_number: "Phone number", PhoneNumber: "Phone number",
    whatsapp_opt_in: "WhatsApp preference",
  };
  return labels[fieldName] || "Form";
}

function presentApiError(data, status) {
  fieldToFocusAfterError = null;
  const detail = data?.detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      const location = Array.isArray(item.loc) ? item.loc.at(-1) : "";
      if (location && location !== "body") {
        fieldToFocusAfterError = form.elements.namedItem(location) ||
                                 form.elements.namedItem("FirstName") ||
                                 form.elements.namedItem("Email") ||
                                 form.elements.namedItem("PhoneNumber");
      }
      const reason = item.msg === "Field required" ? "is required" : item.msg;
      return `${fieldLabel(location)} ${reason}.`;
    });
    return messages.join(" ");
  }
  if (typeof detail === "string") {
    const match = detail.match(/(?:Enter|Please enter) (?:the )?(?:WhatsApp )?number/i);
    if (match) {
      fieldToFocusAfterError = form.elements.namedItem("PhoneNumber") || form.elements.namedItem("contact_number");
    }
    return detail;
  }
  return status === 422
    ? "Some information could not be validated. Please check your entries and try again."
    : "We could not send your enquiry right now. Please try again in a moment.";
}

function showError(message) {
  errorMessage.textContent = message;
  errorPopup.hidden = false;
  document.getElementById("errorRetry").focus();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  if (!form.checkValidity()) {
    form.classList.add("was-validated");
    const firstInvalid = form.querySelector(":invalid");
    if (firstInvalid) firstInvalid.focus();
    return;
  }

  const formData = new FormData(form);
  const rawPayload = Object.fromEntries(formData.entries());

  // Extract first_name and last_name separately, and compute full_name
  let fn = (rawPayload.FirstName || rawPayload.first_name || "").trim();
  let ln = (rawPayload.LastName || rawPayload["Last Name"] || rawPayload.last_name || "").trim();
  let fullName = (rawPayload.full_name || "").trim();

  if (!fullName) {
    fullName = `${fn} ${ln}`.trim();
  } else if (!fn) {
    const parts = fullName.split(/\s+/);
    fn = parts[0] || "";
    ln = parts.slice(1).join(" ") || "";
  }
  if (!fullName && !fn) {
    showError("Please enter your name.");
    return;
  }

  const email = (rawPayload.email || rawPayload.Email || "").trim();
  if (!email) {
    showError("Please enter a valid email address.");
    return;
  }

  // Merge country code with phone number into E.164 international format
  const countryCode = form.elements.namedItem("country_code")?.value || "+91";
  let rawNumber = (rawPayload.contact_number || rawPayload.PhoneNumber || "").trim().replace(/[\s-]/g, "");
  if (!rawNumber) {
    showError("Please enter your phone number.");
    return;
  }

  // Strict mobile number validation
  const digitsOnly = rawNumber.replace(/\D/g, "").replace(/^0+/, "");
  if (countryCode === "+91") {
    if (!/^[6-9]\d{9}$/.test(digitsOnly)) {
      showError("Please enter a valid 10-digit Indian mobile number starting with 6, 7, 8, or 9.");
      const phoneInput = form.elements.namedItem("PhoneNumber") || form.elements.namedItem("contact_number");
      if (phoneInput) phoneInput.focus();
      return;
    }
  } else if (digitsOnly.length < 7 || digitsOnly.length > 15) {
    showError("Please enter a valid mobile number (7 to 15 digits).");
    const phoneInput = form.elements.namedItem("PhoneNumber") || form.elements.namedItem("contact_number");
    if (phoneInput) phoneInput.focus();
    return;
  }

  let finalNumber = rawNumber.startsWith("+") ? `+${digitsOnly}` : `${countryCode}${digitsOnly}`;

  const reqValue = (rawPayload.requirement || rawPayload["What’s on your mind?"] || form.querySelector("textarea")?.value || "").trim();

  const optInEl = form.elements.namedItem("whatsapp_opt_in") || document.getElementById("i0m1w");
  const whatsappOptIn = optInEl ? Boolean(optInEl.checked) : false;

  const payload = {
    first_name: fn,
    last_name: ln,
    full_name: fullName,
    email: email,
    contact_number: finalNumber,
    requirement: reqValue,
    whatsapp_opt_in: whatsappOptIn,
  };

  submitBtn.disabled = true;
  submitBtn.textContent = "Submitting...";

  try {
    const res = await fetch("/api/contact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (res.ok) {
      if (whatsappOptIn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Submit";

        const whatsappUrl = data.whatsapp_url || "https://wa.me/14155238886?text=Hi";
        const phoneMatch = whatsappUrl.match(/wa\.me\/(\d+)/);
        const phoneDigits = phoneMatch ? phoneMatch[1] : "14155238886";

        const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
        const appUrl = `whatsapp://send?phone=${phoneDigits}&text=Hi`;

        // Trigger native WhatsApp application directly on device
        window.location.href = appUrl;

        if (isMobile) {
          setTimeout(() => {
            window.location.href = `https://api.whatsapp.com/send?phone=${phoneDigits}&text=Hi`;
          }, 2500);
        }

        // Refresh the page after submitting the form data
        setTimeout(() => {
          window.location.reload();
        }, 1200);
        return;
      } else {
        // User did not check the WhatsApp checkbox: do not open WhatsApp
        submitBtn.disabled = true;
        submitBtn.textContent = "✓ Submitted Successfully!";
        setTimeout(() => {
          window.location.reload();
        }, 1200);
        return;
      }
    } else {
      showError(presentApiError(data, res.status));
      submitBtn.disabled = false;
      submitBtn.textContent = "Submit";
    }
  } catch (err) {
    showError("We couldn't reach the server. Check your connection and try submitting again.");
    submitBtn.disabled = false;
    submitBtn.textContent = "Submit";
  }
});
