document.getElementById('download-credentials')?.addEventListener('click', () => {
  const cell = value => '"' + (/^[=+\-@\t\r\n]/.test(value.trimStart()) ? "'" + value : value).replaceAll('"', '""') + '"';
  const rows = [['name', 'username', 'initial_password'], ...Array.from(document.querySelectorAll('[data-credential-row]'), row => Array.from(row.cells, td => td.textContent))];
  const url = URL.createObjectURL(new Blob(['\ufeff' + rows.map(row => row.map(cell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'student-login-details.csv';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
