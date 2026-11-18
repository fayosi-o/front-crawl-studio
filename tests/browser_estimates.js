// From this directory: playwright-cli run-code --filename=browser_estimates.js.
async page => {
  const view = await page.context().newPage();
  const errors = [];
  view.on('pageerror', error => errors.push(error.message));
  const assert = (ok, message) => { if (!ok) throw Error(message); };
  try {
    await view.setViewportSize({width: 1440, height: 900});
    await view.goto('http://127.0.0.1:8080/');
    await view.waitForFunction(() => window.LongCatch?.ready());
    const header = view.locator('.lc-header');
    const values = () => header.locator('.lc-stat-value').allTextContents();
    assert(await view.locator('.lc-brand .lc-title').count() === 0, 'Stage title should be hidden');
    assert(await header.locator('.lc-estimate-context > .lc-section-title').textContent() === '',
      'Studio estimate heading should be hidden');
    assert(await header.locator('.lc-hold > :last-child').textContent() === 'Hand hold',
      'Holding status must read Hand hold');
    const studio = await values();
    await view.getByRole('button', {name: 'Expand "Motion details"', exact: true}).click();
    const glide = view.getByRole('slider', {name: 'Glide length', exact: true});
    await glide.focus();
    await glide.press('End');
    await view.waitForFunction(old => document.querySelectorAll('.lc-stat-value')[3].textContent !== old, studio[3]);
    const editedStudio = await values();
    assert(editedStudio[0] !== studio[0], 'Studio estimates did not follow glide changes');
    await view.getByRole('tab', {name: 'Race', exact: true}).click();
    await view.waitForFunction(() => document.querySelector('.lc-estimate-context').textContent.includes('Swimmer A'));
    const a = await values();
    await view.getByRole('button', {name: 'Swimmer B', exact: true}).click();
    await view.waitForFunction(() => document.querySelector('.lc-estimate-context').textContent.includes('Swimmer B'));
    const b = await values();
    assert(a[0] !== b[0], 'Race estimates did not follow selected swimmer');
    assert(await header.locator('.lc-hold > :last-child').textContent() === 'Hand slipping',
      'Slipping status must read Hand slipping');
    const slip = view.getByRole('slider', {name: 'Race Slip', exact: true});
    await slip.focus();
    await slip.press('Home');
    await view.waitForFunction(old => document.querySelector('.lc-stat-value').textContent !== old, b[0]);
    await view.getByRole('button', {name: 'Solo', exact: true}).click();
    await view.waitForFunction(() => document.querySelector('.lc-estimate-context').textContent.includes('Swimmer A'));
    assert(JSON.stringify(await values()) === JSON.stringify(a), 'Solo did not restore swimmer A estimates');
    await view.getByRole('tab', {name: 'Stroke studio', exact: true}).click();
    await view.waitForFunction(() => document.querySelector('.lc-estimate-context > .lc-section-title').textContent.trim() === '');
    assert(JSON.stringify(await values()) === JSON.stringify(editedStudio), 'Switching tabs lost studio estimates');
    const layouts = [];
    for (const width of [1440, 1101, 1100, 1024, 1001, 1000, 900, 780, 768, 601, 600, 541, 540, 390, 320]) {
      await view.setViewportSize({width, height: 900});
      await glide.scrollIntoViewIfNeeded();
      const layout = await header.evaluate(el => {
        const h = el.getBoundingClientRect();
        const labels = [...el.querySelectorAll('.lc-stat-value, .lc-stat-caption, .lc-hold, .lc-section-title, .q-tab__label')];
        return {
          width: innerWidth, height: h.height, top: h.top,
          overflow: document.documentElement.scrollWidth > innerWidth,
          clipped: labels.filter(label => {
            const r = label.getBoundingClientRect();
            return r.left < 0 || r.right > innerWidth + 1 || r.top < h.top || r.bottom > h.bottom + 1
              || label.scrollWidth > label.clientWidth + 1;
          }).map(label => ({text: label.textContent, rect: label.getBoundingClientRect().toJSON(),
            scroll: label.scrollWidth, client: label.clientWidth})),
          overlap: (() => {
            const tabs = el.querySelector('.lc-mode-tabs').getBoundingClientRect();
            const stats = el.querySelector('.lc-estimates').getBoundingClientRect();
            return tabs.right > stats.left && tabs.left < stats.right
              && tabs.bottom > stats.top && tabs.top < stats.bottom;
          })(),
          inline: (() => {
            const tabs = el.querySelector('.lc-mode-tabs').getBoundingClientRect();
            const stats = el.querySelector('.lc-estimates').getBoundingClientRect();
            return tabs.top < stats.bottom && stats.top < tabs.bottom;
          })(),
        };
      });
      assert(layout.top >= -1 && layout.top < 2, `Header not pinned at ${width}px`);
      assert(!layout.overflow && !layout.clipped.length, `Estimates clipped at ${width}px: ${JSON.stringify(layout)}`);
      assert(!layout.overlap, `Estimates overlap tabs at ${width}px`);
      assert(layout.inline && layout.height <= 68, `Estimates wrap below tabs at ${width}px: ${JSON.stringify(layout)}`);
      layouts.push(layout);
    }
    // At mobile widths a focused control must not be hidden behind the sticky header.
    await glide.focus();
    await glide.press('Home');
    const control = await glide.boundingBox(), top = await header.boundingBox();
    assert(control.y >= top.y + top.height && control.y + control.height <= 900,
      'Focused control is obscured by the sticky header');
    await view.getByRole('tab', {name: 'Race', exact: true}).click();
    await view.waitForFunction(() => document.querySelector('.lc-estimate-context').textContent.includes('Swimmer A'));
    await view.getByRole('button', {name: 'Expand "Motion details"', exact: true}).click();
    const raceGlide = view.getByRole('slider', {name: 'Race Glide length', exact: true});
    await raceGlide.focus();
    await raceGlide.press('End');
    await view.waitForFunction(old => document.querySelector('.lc-stat-value').textContent !== old, a[0]);
    const raceHeader = await header.boundingBox(), raceControl = await raceGlide.boundingBox();
    assert(Math.abs(raceHeader.y) < 1 && raceControl.y >= raceHeader.height,
      'Mobile race edits hide the estimates or the focused slider');
    assert(errors.length === 0, errors.join('\n'));
    return {checks: 'passed', layouts, studio, editedStudio, swimmerA: a, swimmerB: b};
  } finally {
    await view.close();
  }
}
