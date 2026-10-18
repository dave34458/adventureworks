/* On-demand search for the .ac boxes rendered by core/widgets.py (SearchSelect):
   fetches up to 20 matching records from the field's autocomplete URL as you type.
   No dependencies; one handler per box, shared by every table's edit form. */
document.addEventListener("DOMContentLoaded", () => {
  for (const box of document.querySelectorAll(".ac")) {
    const text = box.querySelector('input[type="text"]');
    const hidden = box.querySelector('input[type="hidden"]');
    const list = document.createElement("ul");
    list.className = "ac-results";
    box.append(list);
    let selected = text.value;
    let timer, ctrl;

    const close = () => (list.innerHTML = "");
    const choose = (li) => {
      hidden.value = li.dataset.id;
      selected = text.value = li.textContent;
      close();
    };
    const load = async () => {
      ctrl?.abort();
      ctrl = new AbortController();
      try {
        const res = await fetch(text.dataset.url + "?q=" + encodeURIComponent(text.value), { signal: ctrl.signal });
        list.innerHTML = "";
        for (const item of (await res.json()).results) {
          const li = document.createElement("li");
          li.textContent = item.text;
          li.dataset.id = item.id;
          li.addEventListener("mousedown", (e) => { e.preventDefault(); choose(li); });
          list.append(li);
        }
      } catch (e) { /* aborted while typing, or offline */ }
    };

    text.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 200); });
    text.addEventListener("focus", () => { if (!list.children.length) load(); });
    text.addEventListener("blur", () => setTimeout(() => { close(); text.value = selected; }, 150));
    text.addEventListener("keydown", (e) => {
      const items = [...list.children];
      let i = items.findIndex((li) => li.classList.contains("on"));
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        i = e.key === "ArrowDown" ? Math.min(i + 1, items.length - 1) : Math.max(i - 1, 0);
        items.forEach((li, n) => li.classList.toggle("on", n === i));
        items[i]?.scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter" && items[i]) {
        e.preventDefault();
        choose(items[i]);
      } else if (e.key === "Escape") {
        close();
      }
    });
  }
});
