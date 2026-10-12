// Estados y solicitudes del componente real, sin dependencias de navegador.
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../reservations/static/reservations/dashboard_insights.js'), 'utf8');

function component(fetch) {
    let submit;
    const form = {action: '/reservas/admin/dashboard/analisis/', fields: {
        csrfmiddlewaretoken: 'csrf-test', cancha: '101', origen: 'SYNTHETIC'
    }, addEventListener(name, callback) { assert.equal(name, 'submit'); submit = callback; }};
    const button = {disabled: false, textContent: 'Generar análisis'};
    const result = {dataset: {state: 'IDLE'}, children: [], attributes: {},
        replaceChildren() { this.children = []; this.innerHTML = ''; },
        append(node) { this.children.push(node); },
        setAttribute(key, value) { this.attributes[key] = value; },
        removeAttribute(key) { delete this.attributes[key]; }};
    const elements = {'dashboard-analysis-form': form, 'generate-analysis': button, 'dashboard-analysis-result': result};
    const document = {getElementById: id => elements[id], createElement: () => ({})};
    class FormData { constructor(input) { this.fields = {...input.fields}; } }
    vm.runInNewContext(source, {document, fetch, FormData});
    return {form, button, result, submit: () => submit({preventDefault() {}})};
}

test('no automatic call; POST carries CSRF and transitions IDLE → LOADING → SUCCESS', async () => {
    let calls = 0;
    let finish;
    const gate = new Promise(resolve => { finish = resolve; });
    const ui = component(async (url, options) => {
        calls++;
        assert.equal(url, '/reservas/admin/dashboard/analisis/');
        assert.equal(options.method, 'POST');
        assert.equal(options.credentials, 'same-origin');
        assert.equal(options.body.fields.csrfmiddlewaretoken, 'csrf-test');
        assert.equal(options.body.fields.cancha, '101');
        await gate;
        return {json: async () => ({state: 'SUCCESS', html: '<p>Análisis validado</p>'})};
    });
    assert.equal(calls, 0);
    const first = ui.submit();
    assert.equal(ui.result.dataset.state, 'LOADING');
    assert.equal(ui.button.disabled, true);
    assert.equal(ui.result.attributes['aria-busy'], 'true');
    await ui.submit(); // No permite repetir mientras hay una solicitud pendiente.
    assert.equal(calls, 1);
    finish();
    await first;
    assert.equal(ui.result.dataset.state, 'SUCCESS');
    assert.equal(ui.result.innerHTML, '<p>Análisis validado</p>');
    assert.equal(ui.button.disabled, false);
    assert.equal(ui.result.attributes['aria-busy'], undefined);
});

test('validated server error is rendered and enables a new manual attempt', async () => {
    const ui = component(async () => ({json: async () => ({state: 'ERROR', html: '<p>No disponible</p>'})}));
    await ui.submit();
    assert.equal(ui.result.dataset.state, 'ERROR');
    assert.equal(ui.button.disabled, false);
    assert.equal(ui.result.innerHTML, '<p>No disponible</p>');
});

test('network failure, expired session and malformed response give safe ERROR state', async () => {
    for (const fetch of [async () => { throw new Error('private transport text'); },
                        async () => ({redirected: true}),
                        async () => ({json: async () => ({state: 'UNKNOWN', html: '<script>bad</script>'})})]) {
        const ui = component(fetch);
        await ui.submit();
        assert.equal(ui.result.dataset.state, 'ERROR');
        assert.equal(ui.button.disabled, false);
        assert.match(ui.result.children[0].textContent, /indicadores siguen disponibles/);
        assert.doesNotMatch(ui.result.children[0].textContent, /private transport/);
        assert.equal(ui.result.innerHTML, '');
    }
});

test('disabled button does not request an unsupported context', async () => {
    let calls = 0;
    const ui = component(async () => { calls++; });
    ui.button.disabled = true;
    await ui.submit();
    assert.equal(calls, 0);
    assert.equal(ui.result.dataset.state, 'IDLE');
});
