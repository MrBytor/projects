(() => {
  const rows = [...document.querySelectorAll('.bank-question')];
  const week = document.getElementById('filter-week');
  const difficulty = document.getElementById('filter-difficulty');
  const query = document.getElementById('filter-query');
  const checkboxes = rows.map(row => row.querySelector('input[type=checkbox]'));
  const count = document.getElementById('selection-count');
  const selected = () => checkboxes.filter(box => box.checked).length;
  function update() {
    const term = query.value.toLocaleLowerCase().trim();
    rows.forEach(row => { row.hidden = Boolean((week.value && row.dataset.week !== week.value) || (difficulty.value && row.dataset.difficulty !== difficulty.value) || (term && !row.dataset.search.toLocaleLowerCase().includes(term))); });
    count.textContent = selected() + ' / 50 selected';
    document.getElementById('visible-count').textContent = rows.filter(row => !row.hidden).length + ' questions shown';
  }
  [week, difficulty, query].forEach(input => input.addEventListener('input', update));
  checkboxes.forEach(box => box.addEventListener('change', () => {
    if (selected() > 50) { box.checked = false; count.textContent = 'Limit reached: choose up to 50 questions.'; }
    else update();
  }));
  document.getElementById('select-visible').addEventListener('click', () => {
    let total = selected();
    for (const row of rows) {
      const box = row.querySelector('input');
      if (!row.hidden && !box.checked && total < 50) { box.checked = true; total++; }
    }
    update();
  });
  document.getElementById('clear-selection').addEventListener('click', () => { checkboxes.forEach(box => { box.checked = false; }); update(); });
  update();
})();
