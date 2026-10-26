const OPTIONS = {
  planning_to_buy: [
    "Immediately", "Within 1 Month", "Within 3 Months", "Within 6 Months",
    "Within 12 Months", "More Than 1 Year", "Just Exploring / Researching",
  ],
  budget_range: [
    "Up to 25 lakh", "25 lakh - 50 lakh", "50 lakh - 1 crore",
    "1 crore - 2 crore", "Above 2 crore",
  ],
  payment_option: [
    "Bank Finance with EMI", "Full Cash Payment", "Home Loan (Mortgage)",
    "Down Payment Plan", "Construction-Linked Payment Plan (CLP)",
    "Possession-Linked Payment Plan (PLP)", "Installment Payment Plan",
    "Developer Financing", "Rent-to-Own Scheme", "Part Cash + Home Loan",
    "Part Payment with Balance at Registration", "Flexible Payment Plan",
    "Subvention Scheme (Developer Pays Pre-EMI)",
    "Joint Home Loan (Co-applicant Financing)",
    "NRI Payment Plan (for Overseas Buyers)",
  ],
  bhk_preference: [
    "1 RK", "1 BHK", "2 BHK", "2.5 BHK", "3 BHK", "3.5 BHK",
    "4 BHK", "5 BHK+", "Villa", "Penthouse",
  ],
};

const form = document.getElementById("enquiryForm");
const submitBtn = document.getElementById("submitBtn");
const mobile = document.getElementById("mobile_number");
const popup = document.getElementById("successPopup");
const errorPopup = document.getElementById("errorPopup");
const errorMessage = document.getElementById("errorMessage");
const errorTitle = document.getElementById("errorTitle");
let fieldToFocusAfterError = null;

function showPopup() {
  popup.hidden = false;
  document.getElementById("popupOk").focus();
}
function hidePopup() {
  popup.hidden = true;
}
document.getElementById("popupOk").addEventListener("click", hidePopup);
document.getElementById("popupClose").addEventListener("click", hidePopup);
popup.addEventListener("click", (e) => { if (e.target === popup) hidePopup(); });

function hideErrorPopup() {
  errorPopup.hidden = true;
  if (fieldToFocusAfterError) fieldToFocusAfterError.focus();
}
document.getElementById("errorRetry").addEventListener("click", hideErrorPopup);
errorPopup.addEventListener("click", (e) => { if (e.target === errorPopup) hideErrorPopup(); });

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    hidePopup();
    if (!errorPopup.hidden) hideErrorPopup();
  }
});

function fieldLabel(fieldName) {
  const labels = {
    first_name: "First name",
    last_name: "Last name",
    email: "Email",
    mobile_number: "Mobile number",
    location_preference: "Location preference",
    planning_to_buy: "Planning to buy",
    budget_range: "Budget range",
    payment_option: "Payment option",
    bhk_preference: "BHK preference",
    remarks_requirements: "Remarks / requirements",
  };
  return labels[fieldName] || "Field";
}

function presentApiError(data, status) {
  fieldToFocusAfterError = null;
  const detail = data?.detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      const location = Array.isArray(item.loc) ? item.loc.at(-1) : "";
      if (location && location !== "body") fieldToFocusAfterError = form.elements.namedItem(location);
      const reason = item.msg === "Field required" ? "is required" : item.msg;
      return `${fieldLabel(location)} ${reason}.`;
    });
    return messages.join(" ");
  }
  if (typeof detail === "string") {
    if (/location/i.test(detail)) fieldToFocusAfterError = form.elements.namedItem("location_preference");
    else if (/mobile|phone/i.test(detail)) fieldToFocusAfterError = form.elements.namedItem("mobile_number");
    else if (/email/i.test(detail)) fieldToFocusAfterError = form.elements.namedItem("email");
    return detail;
  }
  return status === 422
    ? "Some information could not be validated. Please check your entries and try again."
    : "We could not save your enquiry right now. Please try again in a moment.";
}

function showError(message, title = "CHECK YOUR DETAILS", field = null) {
  if (errorTitle) errorTitle.textContent = title;
  errorMessage.textContent = message;
  fieldToFocusAfterError = field;
  errorPopup.hidden = false;
  document.getElementById("errorRetry").focus();
}

// Fill the dropdowns
for (const [id, list] of Object.entries(OPTIONS)) {
  const select = document.getElementById(id);
  select.add(new Option("Select an option", ""));
  list.forEach((item) => select.add(new Option(item, item)));
}

// Mobile: optional +, then 10-15 digits (spaces and hyphens allowed)
function checkMobile() {
  const digits = mobile.value.replace(/[\s-]/g, "");
  mobile.setCustomValidity(/^\+?[0-9]{10,15}$/.test(digits) ? "" : "invalid");
}
mobile.addEventListener("input", checkMobile);

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  checkMobile();

  if (!form.checkValidity()) {
    form.classList.add("was-validated");
    const invalidField = form.querySelector(":invalid");
    if (invalidField) {
      invalidField.focus();
      let label = invalidField.previousElementSibling ? invalidField.previousElementSibling.textContent.replace("*", "").trim() : "field";
      showError(`Please fill in or correct the ${label} before submitting.`, "CHECK YOUR DETAILS", invalidField);
    }
    return;
  }

  const payload = {};
  new FormData(form).forEach((value, key) => (payload[key] = value.trim()));

  submitBtn.disabled = true;
  submitBtn.textContent = "Submitting...";

  try {
    const res = await fetch("/api/enquiry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (res.ok) {
      form.reset();
      form.classList.remove("was-validated");
      showPopup();
    } else if (res.status === 422) {
      showError(presentApiError(data, 422), "CHECK YOUR DETAILS");
    } else {
      showError(presentApiError(data, res.status), "UNABLE TO SUBMIT");
    }
  } catch (err) {
    showError("Could not reach the server. Please check your internet connection and try again.", "CONNECTION ERROR");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Submit Enquiry";
  }
});

// ---- Location suggestions while typing (OpenStreetMap data via the free Photon service)
const locInput = document.getElementById("location_preference");
const locList = document.getElementById("locList");
let locTimer, locAbort, locItems = [], locActive = -1;

function hideLocations() {
  locList.hidden = true;
  locActive = -1;
}

function showLocMessage(text) {
  locItems = [];
  locActive = -1;
  locList.innerHTML = "";
  const li = document.createElement("li");
  li.className = "muted";
  li.textContent = text;
  locList.appendChild(li);
  locList.hidden = false;
}

function renderLocations() {
  if (!locItems.length) {
    showLocMessage("No suggestions found. You can enter the place name and it will be verified when you submit.");
    return;
  }
  locList.innerHTML = "";
  locActive = -1;
  locItems.forEach((label, i) => {
    const li = document.createElement("li");
    li.setAttribute("role", "option");
    li.dataset.i = i;
    li.textContent = label;
    locList.appendChild(li);
  });
  locList.hidden = false;
}

function pickLocation(i) {
  locInput.value = locItems[i];
  hideLocations();
}

function setActive(n) {
  const opts = locList.querySelectorAll("li[data-i]");
  if (!opts.length) return;
  locActive = (n + opts.length) % opts.length;
  opts.forEach((o, idx) => o.classList.toggle("active", idx === locActive));
  opts[locActive].scrollIntoView({ block: "nearest" });
}

async function searchLocations(q) {
  if (locAbort) locAbort.abort();
  locAbort = new AbortController();
  showLocMessage("Searching...");
  const params = new URLSearchParams({ q });
  try {
    const res = await fetch("/api/locations?" + params, { signal: locAbort.signal });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    locItems = data.locations || [];
    renderLocations();
  } catch (err) {
    if (err.name === "AbortError") return;
    console.error("Location search failed:", err);
    showLocMessage("Suggestions are unavailable. You can still submit a place name for verification.");
  }
}

locInput.addEventListener("input", () => {
  clearTimeout(locTimer);
  const q = locInput.value.trim();
  if (q.length < 3) { hideLocations(); return; }
  locTimer = setTimeout(() => searchLocations(q), 350);
});
locInput.addEventListener("keydown", (e) => {
  if (locList.hidden) return;
  if (e.key === "ArrowDown") { e.preventDefault(); setActive(locActive + 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); setActive(locActive - 1); }
  else if (e.key === "Enter" && locActive >= 0) { e.preventDefault(); pickLocation(locActive); }
  else if (e.key === "Escape") { hideLocations(); }
});
locInput.addEventListener("blur", hideLocations);
locList.addEventListener("mousedown", (e) => {
  const li = e.target.closest("li[data-i]");
  if (li) { e.preventDefault(); pickLocation(Number(li.dataset.i)); }
});
