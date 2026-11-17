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

        const [logData, screenshotData] = await Promise.all([
          fetchJson(logsUrl),
          fetchJson(screenshotsUrl)
        ]);

        appendLogEntries(elements.logs, logData.logs);
        renderScreenshots(elements.screenshots, screenshotData.screenshots);

        if (status.status !== "running") {
          shouldContinue = false;
          if (elements.progress) elements.progress.hidden = true;
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
    card.append(header, grid);
    history.appendChild(card);

    return card;
  }

  function startPollingForCard(taskName, runId, card, options) {
    const statusBadge = card
      ? card.querySelector("[data-run-status-badge]")
      : null;

    const elements = {
      statusBadge,
      logs: card ? card.querySelector("[data-run-logs]") : null,
      screenshots: card ? card.querySelector("[data-run-screenshots]") : null,
      errorBox: card ? card.querySelector("[data-run-error]") : null,
      message: options.message || null,
      progress: options.progress || null,
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
              progress: activeBox ? activeBox.querySelector(".progress-track") : null,
              stopButton,
              runButton: button
            });
          } else {
            startPollingForCard(taskName, result.run_id, null, {
              message: activeMessage,
              progress: activeBox ? activeBox.querySelector(".progress-track") : null,
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
