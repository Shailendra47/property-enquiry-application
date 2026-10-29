/**
 * Profilent Real Flag Country Code Picker
 * Renders real high-res SVG/PNG country flags on all operating systems (including Windows).
 */
(function () {
  const COUNTRIES = [
    { iso: "in", name: "India", code: "+91" },
    { iso: "ae", name: "United Arab Emirates", code: "+971" },
    { iso: "us", name: "United States", code: "+1" },
    { iso: "gb", name: "United Kingdom", code: "+44" },
    { iso: "ca", name: "Canada", code: "+1" },
    { iso: "au", name: "Australia", code: "+61" },
    { iso: "sg", name: "Singapore", code: "+65" },
    { iso: "sa", name: "Saudi Arabia", code: "+966" },
    { iso: "qa", name: "Qatar", code: "+974" },
    { iso: "om", name: "Oman", code: "+968" },
    { iso: "kw", name: "Kuwait", code: "+965" },
    { iso: "bh", name: "Bahrain", code: "+973" },
    { iso: "de", name: "Germany", code: "+49" },
    { iso: "fr", name: "France", code: "+33" },
    { iso: "nz", name: "New Zealand", code: "+64" },
    { iso: "za", name: "South Africa", code: "+27" },
    { iso: "my", name: "Malaysia", code: "+60" },
    { iso: "np", name: "Nepal", code: "+977" },
    { iso: "bd", name: "Bangladesh", code: "+880" }
  ];

  function getFlagUrl(iso) {
    return `https://flagcdn.com/w40/${iso.toLowerCase()}.png`;
  }

  function initPicker(container) {
    if (!container || container.dataset.pickerInit) return;
    container.dataset.pickerInit = "true";

    const btn = container.querySelector(".country-picker-btn");
    const menu = container.querySelector(".country-dropdown-menu");
    const list = container.querySelector(".country-list");
    const searchInput = container.querySelector(".country-search-input");
    const hiddenInput = container.querySelector('input[name="country_code"]') || container.querySelector("#country_code");
    const flagImg = container.querySelector(".country-flag-img");
    const dialCodeSpan = container.querySelector(".country-dial-code");

    let currentSelected = COUNTRIES[0];

    function renderList(filter = "") {
      const q = filter.trim().toLowerCase();
      const filtered = COUNTRIES.filter(c => 
        c.name.toLowerCase().includes(q) || 
        c.code.includes(q) || 
        c.iso.includes(q)
      );

      list.innerHTML = "";
      if (filtered.length === 0) {
        const noResult = document.createElement("li");
        noResult.className = "country-no-result";
        noResult.textContent = "No countries found";
        list.appendChild(noResult);
        return;
      }

      filtered.forEach(c => {
        const li = document.createElement("li");
        li.className = `country-item ${c.iso === currentSelected.iso ? "active" : ""}`;
        li.dataset.iso = c.iso;
        li.dataset.code = c.code;

        li.innerHTML = `
          <img src="${getFlagUrl(c.iso)}" class="country-flag-img" width="22" height="15" alt="${c.iso.toUpperCase()}">
          <span class="country-item-name">${c.name}</span>
          <span class="country-item-code">${c.code}</span>
        `;

        li.addEventListener("click", () => {
          selectCountry(c);
          closeDropdown();
        });

        list.appendChild(li);
      });
    }

    function selectCountry(country) {
      currentSelected = country;
      if (flagImg) {
        flagImg.src = getFlagUrl(country.iso);
        flagImg.alt = country.iso.toUpperCase();
      }
      if (dialCodeSpan) {
        dialCodeSpan.textContent = country.code;
      }
      if (hiddenInput) {
        hiddenInput.value = country.code;
        hiddenInput.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    function openDropdown() {
      menu.hidden = false;
      btn.setAttribute("aria-expanded", "true");
      if (searchInput) {
        searchInput.value = "";
        renderList();
        setTimeout(() => searchInput.focus(), 50);
      } else {
        renderList();
      }
    }

    function closeDropdown() {
      menu.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    }

    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (menu.hidden) {
        // Close any other open pickers
        document.querySelectorAll(".country-dropdown-menu").forEach(m => m.hidden = true);
        openDropdown();
      } else {
        closeDropdown();
      }
    });

    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        renderList(e.target.value);
      });
      searchInput.addEventListener("click", (e) => {
        e.stopPropagation();
      });
    }

    document.addEventListener("click", (e) => {
      if (!container.contains(e.target)) {
        closeDropdown();
      }
    });

    // Initial render
    renderList();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      document.querySelectorAll(".custom-country-picker").forEach(initPicker);
    });
  } else {
    document.querySelectorAll(".custom-country-picker").forEach(initPicker);
  }

  // Also support dynamic init
  window.initCustomCountryPickers = function () {
    document.querySelectorAll(".custom-country-picker").forEach(initPicker);
  };
})();

