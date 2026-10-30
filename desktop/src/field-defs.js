/**
 * 共用配置值操作；Node.js 与配置页面使用同一实现。
 * 字段和界面文案来自 config-fields.json，不依赖 Electron 或文件系统。
 */
(function exposeConfigFields(root, factory) {
  'use strict';
  const helpers = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = helpers;
  } else {
    root.launcherConfigFields = helpers;
  }
})(globalThis, function createConfigFields() {
  'use strict';

  function requireRecord(value) {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
      throw new TypeError('Configuration values must be an object');
    }
  }

  function getDefaultValues(definitions) {
    return Object.fromEntries(definitions.fields.map((field) => [field.name, field.default]));
  }

  function selectKnownValues(definitions, values) {
    requireRecord(values);
    const selected = {};
    for (const field of definitions.fields) {
      if (Object.hasOwn(values, field.name)) selected[field.name] = values[field.name];
    }
    return selected;
  }

  function validateFieldValue(definition, value) {
    if (definition.type === 'bool') {
      return typeof value === 'boolean'
        ? { valid: true, value }
        : { valid: false, code: 'invalid_boolean' };
    }
    if (definition.type === 'str') {
      return typeof value === 'string'
        ? { valid: true, value }
        : { valid: false, code: 'invalid_string' };
    }
    if (definition.type !== 'int') {
      throw new TypeError(`Unsupported configuration type: ${definition.type}`);
    }
    if (!Number.isInteger(value)) return { valid: false, code: 'invalid_integer' };
    if (!Number.isSafeInteger(value)) return { valid: false, code: 'unsafe_integer' };
    if (definition.min !== undefined && value < definition.min) {
      return { valid: false, code: 'below_minimum', min: definition.min };
    }
    if (definition.max !== undefined && value > definition.max) {
      return { valid: false, code: 'above_maximum', max: definition.max };
    }
    return { valid: true, value };
  }

  function parseFieldInput(definition, rawValue) {
    if (definition.type !== 'int') return validateFieldValue(definition, rawValue);
    if (typeof rawValue !== 'string' || !/^[+-]?\d+$/.test(rawValue.trim())) {
      return { valid: false, code: 'invalid_integer' };
    }
    return validateFieldValue(definition, Number(rawValue.trim()));
  }

  function validateConfigValues(definitions, values, partial = false) {
    requireRecord(values);
    const errors = {};
    for (const field of definitions.fields) {
      if (!Object.hasOwn(values, field.name)) {
        if (!partial) errors[field.name] = { valid: false, code: 'missing_field' };
        continue;
      }
      const result = validateFieldValue(field, values[field.name]);
      if (!result.valid) errors[field.name] = result;
    }
    return { valid: Object.keys(errors).length === 0, errors };
  }

  function formatFieldError(definitions, name, result) {
    const template = definitions.ui.validation[result.code];
    if (typeof template !== 'string') {
      throw new TypeError(`Unknown configuration error: ${result.code}`);
    }
    return `${name}: ${template.replace('{min}', String(result.min)).replace('{max}', String(result.max))}`;
  }

  function assertConfigValues(definitions, values, partial = false) {
    const result = validateConfigValues(definitions, values, partial);
    if (!result.valid) {
      throw new TypeError(Object.entries(result.errors)
        .map(([name, error]) => formatFieldError(definitions, name, error)).join('\n'));
    }
  }

  function buildCliArgs(definitions, overrides) {
    const selected = selectKnownValues(definitions, overrides);
    assertConfigValues(definitions, selected, true);
    const args = [];
    for (const field of definitions.fields) {
      if (Object.hasOwn(selected, field.name)) {
        args.push(field.cliArg, String(selected[field.name]));
      }
    }
    return args;
  }

  return {
    getDefaultValues,
    selectKnownValues,
    parseFieldInput,
    validateConfigValues,
    assertConfigValues,
    formatFieldError,
    buildCliArgs,
  };
});
