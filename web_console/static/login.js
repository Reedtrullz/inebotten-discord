(function () {
  function setThemeLabel() {
    var icon = document.getElementById("theme-icon");
    if (!icon) return;
    icon.textContent = document.documentElement.classList.contains("light") ? "Mørk" : "Lys";
  }

  function toggleTheme() {
    var html = document.documentElement;
    if (html.classList.contains("light")) {
      html.classList.remove("light");
      html.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else {
      html.classList.remove("dark");
      html.classList.add("light");
      localStorage.setItem("theme", "light");
    }
    setThemeLabel();
  }

  document.addEventListener("DOMContentLoaded", function () {
    setThemeLabel();
    var toggle = document.getElementById("login-theme-toggle");
    if (toggle) toggle.addEventListener("click", toggleTheme);
  });
})();
