/*
 * Content planner board + calendar, as a Stimulus controller on Wagtail's own Stimulus app.
 * Every change is a POST to the planner's admin endpoints; the server runs the Wagtail action, then
 * Wagtail's w-swap controller re-renders the results in place and Wagtail's message bar says what happened.
 * Wagtail's dialogs are teleported to <body>, so dialog parts are found by id rather than as targets.
 */
const DIALOGS = [
  'wkcc-schedule-dialog',
  'wkcc-confirm-dialog',
  'wkcc-card-dialog',
];

window.wagtail.app.register(
  'wkcc-board',
  class extends window.StimulusModule.Controller {
    static values = {
      csrf: String,
      resultsUrl: String,
      networkError: String,
      notAllowed: String,
      serverError: String,
    };

    connect() {
      this.onDocumentClick = (event) => {
        if (event.target.closest('[data-wkcc-ready-without-date]')) {
          event.preventDefault();
          this.readyWithoutDate();
        } else if (event.target.closest('#wkcc-confirm-go') && this.confirmed) {
          event.preventDefault();
          const go = this.confirmed;
          this.confirmed = null;
          this.hideDialog('wkcc-confirm-dialog');
          go({ confirm: '1' });
        }
      };
      // Card Move… forms, on the board and in the quick-view dialog (which Wagtail moves to <body>).
      this.onDocumentSubmit = (event) => {
        const form = event.target.closest('form[data-wkcc-move-form]');
        const card = form && form.closest('[data-page-id]');
        if (!card) return;
        event.preventDefault();
        const stage = form.elements.to.value;
        if (stage !== card.dataset.stage) this.moveCard(card, stage);
      };
      document.addEventListener('click', this.onDocumentClick);
      document.addEventListener('submit', this.onDocumentSubmit);
    }

    disconnect() {
      document.removeEventListener('click', this.onDocumentClick);
      document.removeEventListener('submit', this.onDocumentSubmit);
    }

    dragStart(event) {
      this.dragged = event.currentTarget;
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', this.dragged.dataset.pageId);
      this.dragged.classList.add('wkcc-dragging');
    }

    dragEnd() {
      if (this.dragged) this.dragged.classList.remove('wkcc-dragging');
    }

    dragOver(event) {
      if (!this.dragged) return;
      event.preventDefault();
      event.currentTarget.classList.add('wkcc-drop-target');
    }

    dragLeave(event) {
      event.currentTarget.classList.remove('wkcc-drop-target');
    }

    drop(event) {
      event.preventDefault();
      event.currentTarget.classList.remove('wkcc-drop-target');
      const card = this.dragged;
      const stage = event.currentTarget.dataset.stage;
      this.dragged = null;
      if (!card || !stage || stage === card.dataset.stage) return;
      this.moveCard(card, stage);
    }

    moveCard(card, stage) {
      this.confirmFirst(card, (extra) => {
        if (stage === 'ready') {
          this.openSchedule(card, '', extra.confirm || '');
        } else {
          this.post(card.dataset.moveUrl, {
            to: stage,
            token: card.dataset.token,
            ...extra,
          });
        }
      });
    }

    /* Moves that undo Wagtail state (unpublish, unschedule, cancel workflow) are confirmed first. */
    confirmFirst(card, go) {
      if (!card.dataset.undo) {
        go({});
        return;
      }
      document.getElementById('wkcc-confirm-text').textContent =
        card.dataset.undo;
      this.confirmed = go;
      this.showDialog('wkcc-confirm-dialog');
    }

    dropOnDay(event) {
      event.preventDefault();
      event.currentTarget.classList.remove('wkcc-drop-target');
      const card = this.dragged;
      const day = event.currentTarget.dataset.date;
      this.dragged = null;
      if (!card || !day) return;
      if (card.dataset.kind === 'target') {
        this.post(card.dataset.targetUrl, {
          target_date: day,
          token: card.dataset.token,
        });
      } else {
        this.openSchedule(card, `${day}T09:00`, '');
      }
    }

    /* The quick view loads into its dialog with Wagtail's w-swap (the loader form in dialogs.html). */
    openCard(event) {
      event.preventDefault();
      const url = new URL(
        event.currentTarget.getAttribute('href'),
        window.location.href,
      );
      url.searchParams.set('partial', '1');
      const body = document.getElementById('wkcc-card-body');
      body.addEventListener(
        'w-swap:success',
        () => this.showDialog('wkcc-card-dialog'),
        { once: true },
      );
      this.dispatch('open-card', {
        prefix: 'wkcc',
        target: document,
        detail: { url: url.toString() },
      });
    }

    openSchedule(card, when, confirm) {
      const form = document.getElementById('wkcc-schedule-form');
      form.action = card.dataset.scheduleUrl;
      form.dataset.moveUrl = card.dataset.moveUrl;
      form.elements.token.value = card.dataset.token;
      form.elements.go_live_at.value = when;
      form.elements.confirm.value = confirm;
      document.getElementById('wkcc-schedule-title').textContent =
        card.dataset.title;
      this.showDialog('wkcc-schedule-dialog');
    }

    readyWithoutDate() {
      const form = document.getElementById('wkcc-schedule-form');
      this.post(form.dataset.moveUrl, {
        to: 'ready',
        token: form.elements.token.value,
        confirm: form.elements.confirm.value,
      });
    }

    showDialog(id) {
      document
        .getElementById(id)
        .dispatchEvent(new CustomEvent('w-dialog:show'));
    }

    hideDialog(id) {
      const dialog = document.getElementById(id);
      if (dialog) dialog.dispatchEvent(new CustomEvent('w-dialog:hide'));
    }

    async post(url, fields) {
      const data = new FormData();
      Object.entries(fields).forEach(([key, value]) => data.append(key, value));
      let response;
      try {
        response = await fetch(url, {
          method: 'POST',
          body: data,
          headers: {
            'X-CSRFToken': this.csrfValue,
            'Accept': 'application/json',
          },
        });
      } catch {
        this.say(this.networkErrorValue);
        return;
      }
      // Anything other than the planner's JSON is Wagtail's permission redirect (4xx) or a server error.
      const fallback =
        response.status >= 500 ? this.serverErrorValue : this.notAllowedValue;
      const result = await response
        .json()
        .catch(() => ({ ok: false, message: fallback }));
      if (!result.ok) {
        this.say(result.message || fallback);
        return;
      }
      DIALOGS.forEach((id) => this.hideDialog(id));
      await this.refresh();
      this.say(result.message, 'success');
    }

    /* Re-render the results with Wagtail's w-swap, keeping the board's sideways scroll. */
    refresh() {
      const strip = this.element.querySelector('.wkcc-board');
      const scrollLeft = strip ? strip.scrollLeft : 0;
      return new Promise((resolve) => {
        document.addEventListener(
          'w-swap:success',
          () => {
            const newStrip = this.element.querySelector('.wkcc-board');
            if (newStrip) newStrip.scrollLeft = scrollLeft;
            resolve();
          },
          { once: true },
        );
        this.dispatch('refresh', {
          prefix: 'wkcc',
          target: document,
          detail: { url: `${this.resultsUrlValue}${window.location.search}` },
        });
      });
    }

    /* Wagtail's own message bar, as Wagtail's drag-to-reorder uses it. */
    say(text, type = 'error') {
      document.dispatchEvent(
        new CustomEvent('w-messages:add', {
          detail: { clear: true, text, type },
        }),
      );
    }
  },
);
