
document.querySelectorAll('[data-live-schedule]').forEach(async section => {
  const status = section.querySelector('.live-status');
  try {
    const response = await fetch(section.dataset.liveSchedule, {signal: AbortSignal.timeout(20000)});
    if (!response.ok || response.redirected) throw new Error('Schedule unavailable');
    const html = await response.text();
    section.innerHTML = html;
  } catch (error) {
    status.textContent = 'Live schedule unavailable. Saved roster remains below. Reload to retry.';
  }
});
