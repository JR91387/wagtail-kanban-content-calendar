/*
 * In the page editor, show the planner stage beside Wagtail's header toggles, as a status tag linking to
 * the card. The stage comes from the planner's entry in the header ⋯ menu, which stays as the fallback.
 * This runs as a deferred script, before Wagtail's controllers start: the ⋯ dropdown takes its items out of
 * the page when it connects. If Wagtail's header has no toggles, nothing is shown.
 */
(() => {
  const source = document.querySelector('[data-wkcc-stage-label]');
  const toggle = document.querySelector('[data-side-panel-toggle]');
  if (!source || !toggle || document.querySelector('[data-wkcc-stage-tag]')) {
    return;
  }
  const { wkccStageLabel: label, wkccStageDescription: description } =
    source.dataset;
  const tag = document.createElement('a');
  tag.className = 'page-status-tag';
  tag.href = source.getAttribute('href');
  tag.dataset.wkccStageTag = '';
  tag.title = description;
  tag.setAttribute('aria-label', `${description}: ${label}`);
  tag.textContent = label;
  toggle.parentElement.insertBefore(tag, toggle);
})();
