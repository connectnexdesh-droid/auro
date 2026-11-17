(() => {
  "use strict";

  const POLL_INTERVAL_MS = 2000;

  function showMessage(message, kind) {
    const flash = document.getElementById("flash-message");
    if (!flash) return;

    flash.textContent = message;
    flash.className = "flash-message" + (kind ? " " + kind : "");
    flash.hidden = false;
  }

  function setStatusBadge(element, status) {
    if (!element) return;
    element.textContent = status;
    element.className = "status-badge status-" + String(status).toLowerCase();
  }

  function appendLogEntries(container, logs) {
    if (!container || !Array.isArray(logs)) return;

    const existingIds = new Set(
      Array.from(container.querySelectorAll("[data-log-id]"))
        .map((node) => node.getAttribute("data-log-id"))
    );

    if (container.querySelector(".empty-inline")) {
      container.innerHTML = "";
    }

    logs.forEach((entry) => {
      const entryId = String(entry.id);
      if (existingIds.has(entryId)) return;

      const row = document.createElement("div");
      row.className = "log-entry";
      row.setAttribute("data-log-id", entryId);

      const time = document.createElement("time");
      time.textContent = entry.created_at || "";

      const level = document.createElement("span");
      level.className = "log-level log-" + String(entry.level || "info").toLowerCase();
      level.textContent = entry.level || "INFO";

      const message = document.createElement("span");
      message.className = "log-message";
      message.textContent = entry.message || "";

      row.append(time, level, message);
      container.appendChild(row);
      existingIds.add(entryId);
    });

    container.scrollTop = container.scrollHeight;
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remainder = total % 60;

    if (hours) return hours + "h " + minutes + "m";
    if (minutes) return minutes + "m " + remainder + "s";
    return remainder + "s";
  }

  function formatExpectedFinish(timestamp) {
    if (!timestamp) return "Calculating…";
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return "Calculating…";
    return date.toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit"
    });
  }

  function renderProgressTarget(status, target) {
    if (!target) return;

    const total = Math.max(0, Number(status.total_steps) || 0);
    const completed = Math.max(0, Number(status.completed_steps) || 0);
    const current = Math.max(0, Number(status.current_step) || 0);
    const action = String(status.current_action || "Preparing workflow");
    const percent = status.status === "completed" || status.status === "success"
      ? 100
      : Math.max(0, Math.min(100, Number(status.progress_percent) || 0));

    if (target.label) {
      target.label.textContent = total
        ? (status.status === "running" && current
          ? "Step " + current + " of " + total + " · " + action
          : completed + " of " + total + " steps · " + action)
        : action;
    }
    if (target.percent) target.percent.textContent = percent + "%";
    if (target.fill) target.fill.style.width = percent + "%";
    if (target.elapsed) {
      target.elapsed.textContent = formatDuration(status.elapsed_seconds);
    }
    if (target.action) target.action.textContent = action;
    if (target.eta) {
      if (status.status === "running") {
        const finish = formatExpectedFinish(status.expected_finish_at);
        const remaining = status.estimated_remaining_seconds;
        target.eta.textContent = remaining === null || remaining === undefined
          ? finish
          : finish + " · " + formatDuration(remaining) + " left";
      } else {
        target.eta.textContent = status.status === "completed" || status.status === "success"
          ? "Finished"
          : status.status.charAt(0).toUpperCase() + status.status.slice(1);
      }
    }
  }

  function renderTimeline(container, steps, countTarget) {
    if (!container || !Array.isArray(steps)) return;

    const existing = new Map(
      Array.from(container.querySelectorAll("[data-step-id]"))
        .map((node) => [node.getAttribute("data-step-id"), node])
    );

    if (container.querySelector(".empty-inline") && steps.length) {
      container.innerHTML = "";
    }

    steps.forEach((step) => {
      const stepId = String(step.id);
      let item = existing.get(stepId);

      if (!item) {
        item = document.createElement("div");
        item.className = "timeline-item";
        item.setAttribute("data-step-id", stepId);

        const marker = document.createElement("span");
        marker.className = "timeline-marker";

        const copy = document.createElement("div");
        copy.className = "timeline-copy";
        const action = document.createElement("strong");
        action.setAttribute("data-step-action", "");
        const meta = document.createElement("small");
        meta.setAttribute("data-step-meta", "");
        const error = document.createElement("small");
        error.className = "timeline-error";
        error.setAttribute("data-step-error", "");
        error.hidden = true;
        copy.append(action, meta, error);

        const result = document.createElement("span");
        result.className = "timeline-result";
        result.setAttribute("data-step-result", "");

        item.append(marker, copy, result);
        container.appendChild(item);
      }

      item.className = "timeline-item timeline-" + String(step.status || "running");
      const action = item.querySelector("[data-step-action]");
      const meta = item.querySelector("[data-step-meta]");
      const result = item.querySelector("[data-step-result]");
      const error = item.querySelector("[data-step-error]");

      if (action) action.textContent = String(step.action || "action").toUpperCase();
      if (meta) {
        meta.textContent = "Attempt " + step.attempt +
          " · Record " + step.record_index +
          " · Step " + step.step_index;
      }
      if (result) {
        result.textContent = step.duration_ms === null || step.duration_ms === undefined
          ? String(step.status || "running")
          : (Number(step.duration_ms) / 1000).toFixed(1) + "s";
      }
      if (error) {
        error.textContent = step.error || "";
        error.hidden = !step.error;
      }
    });

    if (countTarget) {
      countTarget.textContent = steps.length + (steps.length === 1 ? " action" : " actions");
    }
  }

  function renderScreenshots(container, screenshots) {
    if (!container || !Array.isArray(screenshots)) return;

    const current = new Set(
      Array.from(container.querySelectorAll("a.screenshot-thumb"))
        .map((node) => node.getAttribute("href"))
    );

    if (container.querySelector(".empty-inline") && screenshots.length) {
      container.innerHTML = "";
    }

    screenshots.forEach((shot) => {
      if (!shot.url || current.has(shot.url)) return;

      const link = document.createElement("a");
      link.className = "screenshot-thumb";
      link.href = shot.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";

      const image = document.createElement("img");
      image.src = shot.url;
      image.alt = "Automation screenshot " + (shot.filename || "");
      image.loading = "lazy";

      const caption = document.createElement("span");
      caption.textContent = shot.filename || "Screenshot";

      link.append(image, caption);
      container.appendChild(link);
      current.add(shot.url);
    });
  }

  async function fetchJson(url) {
    const response = await fetch(url, {
      headers: { "Accept": "application/json" },
      cache: "no-store"
    });

    if (!response.ok) {
      let detail = "Request failed (" + response.status + ")";
      try {
        const body = await response.json();
        detail = body.detail || detail;
      } catch (_) {
        // Keep the generic HTTP error when the response is not JSON.
      }
      throw new Error(detail);
    }

    return response.json();
  }

  async function pollRun(taskName, runId, elements) {
    const statusUrl = "/task/" + encodeURIComponent(taskName) +
      "/status/" + encodeURIComponent(runId);
    const logsUrl = "/task/" + encodeURIComponent(taskName) +
      "/logs/" + encodeURIComponent(runId);
    const screenshotsUrl = "/task/" + encodeURIComponent(taskName) +
      "/screenshots/" + encodeURIComponent(runId);

    let shouldContinue = true;

    while (shouldContinue) {
      try {
        const status = await fetchJson(statusUrl);

        setStatusBadge(elements.statusBadge, status.status);
        if (elements.rowStatus) setStatusBadge(elements.rowStatus, status.status);
        if (elements.message) {
          elements.message.textContent = status.finished_at
            ? "Finished at " + status.finished_at
            : "Chrome workflow is running.";
        }

        if (elements.errorBox) {
          if (status.error) {
            elements.errorBox.textContent = status.error;
            elements.errorBox.hidden = false;
          } else {
            elements.errorBox.hidden = true;
          }
        }

        (elements.progressTargets || []).forEach((target) => {
          renderProgressTarget(status, target);
        });
        renderTimeline(elements.timeline, status.timeline, elements.timelineCount);

        const [logData, screenshotData] = await Promise.all([
          fetchJson(logsUrl),
          fetchJson(screenshotsUrl)
        ]);

        appendLogEntries(elements.logs, logData.logs);
        renderScreenshots(elements.screenshots, screenshotData.screenshots);

        if (status.status !== "running") {
          shouldContinue = false;
          if (elements.stopButton) elements.stopButton.disabled = true;
          if (elements.message) {
            elements.message.textContent = status.error
              ? status.error
              : "Run " + status.status + ".";
          }
          if (elements.runButton) elements.runButton.disabled = false;
          if (elements.rowMessage) elements.rowMessage.textContent = "Run " + status.status + ".";
          if (elements.refreshAfterFinish) {
            window.setTimeout(() => window.location.reload(), 1200);
          }
          break;
        }
      } catch (error) {
        if (elements.message) elements.message.textContent = error.message;
        if (elements.rowMessage) elements.rowMessage.textContent = error.message;
      }

      await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
    }
  }

  function findRunCard(taskName, runId) {
    return document.querySelector(
      '[data-run-card][data-task-name="' + CSS.escape(taskName) +
      '"][data-run-id="' + CSS.escape(runId) + '"]'
    );
  }

  function createLiveRunCard(taskName, runId) {
    const history = document.querySelector(".history-panel");
    if (!history) return null;

    const emptyState = history.querySelector(".compact-empty");
    if (emptyState) emptyState.remove();

    const card = document.createElement("article");
    card.className = "run-history-card";
    card.setAttribute("data-run-card", "");
    card.setAttribute("data-task-name", taskName);
    card.setAttribute("data-run-id", runId);
    card.setAttribute("data-run-status", "running");

    const header = document.createElement("div");
    header.className = "run-history-header";

    const main = document.createElement("div");
    main.className = "run-history-main";

    const badge = document.createElement("span");
    badge.className = "status-badge status-running";
    badge.setAttribute("data-run-status-badge", "");
    badge.textContent = "running";

    const id = document.createElement("span");
    id.className = "mono-text run-id";
    id.textContent = runId;

    const started = document.createElement("span");
    started.className = "muted-cell";
    started.textContent = "Started just now";

    main.append(badge, id, started);
    header.append(main);

    const progressPanel = document.createElement("section");
    progressPanel.className = "run-progress-panel history-progress-panel";
    const progressHeading = document.createElement("div");
    progressHeading.className = "run-progress-heading";
    const progressLabel = document.createElement("span");
    progressLabel.setAttribute("data-progress-label", "");
    progressLabel.textContent = "Preparing workflow…";
    const progressPercent = document.createElement("strong");
    progressPercent.setAttribute("data-progress-percent", "");
    progressPercent.textContent = "0%";
    progressHeading.append(progressLabel, progressPercent);

    const progressTrack = document.createElement("div");
    progressTrack.className = "progress-track";
    const progressFill = document.createElement("span");
    progressFill.className = "progress-fill";
    progressFill.setAttribute("data-progress-fill", "");
    progressFill.style.width = "0%";
    progressTrack.appendChild(progressFill);

    const progressStats = document.createElement("div");
    progressStats.className = "run-progress-stats";
    const elapsed = document.createElement("span");
    elapsed.append("Elapsed ");
    const elapsedValue = document.createElement("strong");
    elapsedValue.setAttribute("data-progress-elapsed", "");
    elapsedValue.textContent = "0s";
    elapsed.appendChild(elapsedValue);

    const eta = document.createElement("span");
    eta.append("ETA ");
    const etaValue = document.createElement("strong");
    etaValue.setAttribute("data-progress-eta", "");
    etaValue.textContent = "Calculating…";
    eta.appendChild(etaValue);
    progressStats.append(elapsed, eta);
    progressPanel.append(progressHeading, progressTrack, progressStats);

    const timelineSection = document.createElement("section");
    timelineSection.className = "timeline-section";
    const timelineHeading = document.createElement("div");
    timelineHeading.className = "mini-heading";
    timelineHeading.append("ACTION TIMELINE ");
    const timelineCount = document.createElement("span");
    timelineCount.setAttribute("data-timeline-count", "");
    timelineCount.textContent = "0 actions";
    timelineHeading.appendChild(timelineCount);
    const timeline = document.createElement("div");
    timeline.className = "action-timeline";
    timeline.setAttribute("data-run-timeline", "");
    timeline.appendChild(document.createElement("div"));
    const emptyTimeline = document.createElement("div");
    emptyTimeline.className = "empty-inline";
    emptyTimeline.textContent = "Waiting for the first workflow action…";
    timeline.replaceChildren(emptyTimeline);
    timelineSection.append(timelineHeading, timeline);

    const grid = document.createElement("div");
    grid.className = "run-observability-grid";

    const logSection = document.createElement("section");
    logSection.className = "log-section";
    const logHeading = document.createElement("div");
    logHeading.className = "mini-heading";
    logHeading.textContent = "EXECUTION LOG";
    const logs = document.createElement("div");
    logs.className = "log-list";
    logs.setAttribute("data-run-logs", "");
    logSection.append(logHeading, logs);

    const shotSection = document.createElement("section");
    shotSection.className = "screenshot-section";
    const shotHeading = document.createElement("div");
    shotHeading.className = "mini-heading";
    shotHeading.textContent = "SCREENSHOTS";
    const shots = document.createElement("div");
    shots.className = "screenshot-grid";
    shots.setAttribute("data-run-screenshots", "");
    shotSection.append(shotHeading, shots);

    grid.append(logSection, shotSection);
    card.append(header, progressPanel, timelineSection, grid);
    history.appendChild(card);

    return card;
  }

  function startPollingForCard(taskName, runId, card, options) {
    const statusBadge = card
      ? card.querySelector("[data-run-status-badge]")
      : null;
    const progressTargets = [];

    if (card) {
      progressTargets.push({
        label: card.querySelector("[data-progress-label]"),
        percent: card.querySelector("[data-progress-percent]"),
        fill: card.querySelector("[data-progress-fill]"),
        elapsed: card.querySelector("[data-progress-elapsed]"),
        eta: card.querySelector("[data-progress-eta]"),
        action: card.querySelector("[data-progress-action]")
      });
    }
    if (options.activeProgress) progressTargets.push(options.activeProgress);

    const elements = {
      statusBadge,
      logs: card ? card.querySelector("[data-run-logs]") : null,
      screenshots: card ? card.querySelector("[data-run-screenshots]") : null,
      timeline: card ? card.querySelector("[data-run-timeline]") : null,
      timelineCount: card ? card.querySelector("[data-timeline-count]") : null,
      errorBox: card ? card.querySelector("[data-run-error]") : null,
      message: options.message || null,
      progressTargets,
      stopButton: options.stopButton || null,
      runButton: options.runButton || null,
      rowStatus: options.rowStatus || null,
      rowMessage: options.rowMessage || null,
      refreshAfterFinish: options.refreshAfterFinish || false
    };

    pollRun(taskName, runId, elements);
  }

  document.querySelectorAll("[data-run-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();

      const button = form.querySelector('button[type="submit"]');
      const taskName = form.getAttribute("data-task-name");
      const row = form.closest("[data-task-row]");
      const rowStatus = row ? row.querySelector("[data-task-status]") : null;
      const rowMessage = row ? row.querySelector("[data-run-message]") : null;
      const isDetailForm = form.hasAttribute("data-detail-run-form");

      if (button) button.disabled = true;
      if (rowMessage) rowMessage.textContent = "Queueing run…";

      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { "Accept": "application/json" }
        });

        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "Could not start task.");

        if (rowStatus) setStatusBadge(rowStatus, "running");
        if (rowMessage) rowMessage.textContent = "Run " + result.run_id;

        if (isDetailForm) {
          const activeBox = document.querySelector("[data-active-run]");
          const activeStatus = document.querySelector("[data-active-status]");
          const activeId = document.querySelector("[data-active-run-id]");
          const activeMessage = document.querySelector("[data-active-run-message]");
          const stopButton = document.querySelector("[data-stop-run]");
          const activeProgress = activeBox ? {
            label: activeBox.querySelector("[data-active-step-label]"),
            percent: activeBox.querySelector("[data-active-progress-percent]"),
            fill: activeBox.querySelector("[data-active-progress-fill]"),
            elapsed: activeBox.querySelector("[data-active-elapsed]"),
            eta: activeBox.querySelector("[data-active-eta]")
          } : null;

          if (activeBox) activeBox.hidden = false;
          setStatusBadge(activeStatus, "running");
          if (activeId) activeId.textContent = result.run_id;
          if (activeMessage) activeMessage.textContent = "Chrome workflow is running.";
          if (stopButton) {
            stopButton.disabled = false;
            stopButton.setAttribute("data-stop-url",
              "/task/" + encodeURIComponent(taskName) + "/stop/" +
              encodeURIComponent(result.run_id)
            );
          }

          const card = createLiveRunCard(taskName, result.run_id);
          if (card) {
            startPollingForCard(taskName, result.run_id, card, {
              message: activeMessage,
              activeProgress,
              stopButton,
              runButton: button
            });
          } else {
            startPollingForCard(taskName, result.run_id, null, {
              message: activeMessage,
              activeProgress,
              stopButton,
              runButton: button,
              refreshAfterFinish: true
            });
          }
        } else {
          startPollingForCard(taskName, result.run_id, null, {
            rowStatus,
            rowMessage,
            runButton: button
          });
        }

        showMessage("Automation run started: " + result.run_id, "success");
      } catch (error) {
        if (button) button.disabled = false;
        if (rowMessage) rowMessage.textContent = error.message;
        showMessage(error.message, "error");
      }
    });
  });

  document.querySelectorAll("[data-run-card]").forEach((card) => {
    const taskName = card.getAttribute("data-task-name");
    const runId = card.getAttribute("data-run-id");
    const status = card.getAttribute("data-run-status");

    if (status === "running") {
      startPollingForCard(taskName, runId, card, {});
    }
  });

  const stopButton = document.querySelector("[data-stop-run]");
  if (stopButton) {
    stopButton.addEventListener("click", async () => {
      const stopUrl = stopButton.getAttribute("data-stop-url");
      if (!stopUrl) return;

      stopButton.disabled = true;
      const message = document.querySelector("[data-active-run-message]");
      if (message) message.textContent = "Sending stop request…";

      try {
        const response = await fetch(stopUrl, { method: "POST" });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "Could not stop run.");
        if (message) message.textContent = result.message || "Stop request received.";
      } catch (error) {
        stopButton.disabled = false;
        if (message) message.textContent = error.message;
        showMessage(error.message, "error");
      }
    });
  }

  const uploadForm = document.getElementById("upload-form");
  if (uploadForm) {
    uploadForm.addEventListener("submit", async (event) => {
      event.preventDefault();

      const resultBox = document.getElementById("upload-result");
      const submitButton = uploadForm.querySelector('button[type="submit"]');
      if (submitButton) submitButton.disabled = true;
      if (resultBox) {
        resultBox.className = "form-feedback";
        resultBox.textContent = "Uploading file…";
      }

      try {
        const response = await fetch(uploadForm.action, {
          method: "POST",
          body: new FormData(uploadForm),
          headers: { "Accept": "application/json" }
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "Upload failed.");

        document.querySelectorAll('select[name="input_filename"]').forEach((select) => {
          const option = document.createElement("option");
          option.value = result.filename;
          option.textContent = result.filename;
          select.appendChild(option);
          select.value = result.filename;
        });

        if (resultBox) {
          resultBox.className = "form-feedback success";
          resultBox.textContent = "Uploaded " + result.filename + ". Refresh the page to update the available files list.";
        }
        uploadForm.reset();
        showMessage("Input file uploaded successfully.", "success");
      } catch (error) {
        if (resultBox) {
          resultBox.className = "form-feedback error";
          resultBox.textContent = error.message;
        }
      } finally {
        if (submitButton) submitButton.disabled = false;
      }
    });
  }
})();
