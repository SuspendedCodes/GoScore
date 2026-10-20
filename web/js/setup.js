import { api, $, toast, matchIdFromPath } from './common.js';
import { setupForm } from './setupform.js';
const id = matchIdFromPath();
$('#back').href = `/score/${id}`;
const [presets, m] = await Promise.all([api('GET', '/api/presets'), api('GET', `/api/matches/${id}`)]);
const form = setupForm(presets, m);
$('#form').append(form);
$('#save').onclick = async () => {
  try { await api('POST', `/api/matches/${id}/setup`, { patch: form.value(), reason: $('#why').value }); toast('Saved', 'ok'); }
  catch (e) { toast(e.message, 'bad'); }
};
