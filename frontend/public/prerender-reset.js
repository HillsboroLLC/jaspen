(() => {
  const root = document.getElementById('root');
  if (root?.dataset.prerendered === 'true') {
    root.replaceChildren();
    delete root.dataset.prerendered;
  }
})();
