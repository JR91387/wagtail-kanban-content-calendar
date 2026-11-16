/** @type {import('stylelint').Config} */
export default {
  extends: ['@wagtail/stylelint-config-wagtail'],
  rules: {
    // Colours come only from Wagtail's admin tokens (var(--w-color-…)), so light, dark and
    // high-contrast themes follow Wagtail.
    'color-no-hex': true,
    'color-named': 'never',
    'function-disallowed-list': [
      'rgb',
      'rgba',
      'hsl',
      'hsla',
      'hwb',
      'lab',
      'lch',
    ],
  },
};
