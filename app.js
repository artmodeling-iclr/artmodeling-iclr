const instances = {
  cabinet16: { title: "Cabinet 16", category: "Cabinet", index: "01 / 09" },
  cabinet17: { title: "Cabinet 17", category: "Cabinet", index: "02 / 09" },
  dressing_case2: { title: "Dressing Case 2", category: "Dressing case", index: "03 / 09" },
  firstkit2: { title: "First Aid Kit 2", category: "First aid kit", index: "04 / 09" },
  fryer1: { title: "Air Fryer 1", category: "Air fryer", index: "05 / 09" },
  laptop1: { title: "Laptop 1", category: "Laptop", index: "06 / 09" },
  microwave1: { title: "Microwave 1", category: "Microwave", index: "07 / 09" },
  oven4: { title: "Oven 4", category: "Oven", index: "08 / 09" },
  ricebucket1: { title: "Rice Bucket 1", category: "Rice bucket", index: "09 / 09" },
};

const notes = {
  start: "Normal-pose RGB capture at the start articulation state.",
  end: "Normal-pose RGB capture at the end articulation state.",
  supplemental: "A repositioned capture reveals surfaces hidden in the normal pose. Its folder name does not describe articulation state.",
  motion: "Selected interaction frames, shown in RGB and colorized depth.",
  geometry: "Geometry preview exported from the USD asset. Colors are approximate; the source materials are not reproduced here.",
};

const dialog = document.querySelector("#instance-dialog");
const dialogContent = document.querySelector("#dialog-content");
const dialogTitle = document.querySelector("#dialog-title");
const dialogCategory = document.querySelector("#dialog-category");
const dialogNote = document.querySelector("#dialog-note");
const dialogCounter = document.querySelector("#dialog-counter");
const dialogTabs = [...document.querySelectorAll(".dialog-tabs [role='tab']")];
let currentId = null;
let currentTab = "start";

const asset = (id, name) => `assets/objects/${id}/${name}.webp`;

function createImage(src, alt) {
  const image = document.createElement("img");
  image.src = src;
  image.alt = alt;
  image.decoding = "async";
  return image;
}

function renderImageTab(id, tab) {
  const wrapper = document.createElement("div");
  wrapper.className = "dialog-media-single";
  wrapper.append(createImage(asset(id, tab), `${instances[id].title}: ${tab === "supplemental" ? "supplemental pose" : `${tab} articulation state`}`));
  dialogContent.append(wrapper);
}

function renderMotionTab(id) {
  const grid = document.createElement("div");
  grid.className = "dialog-motion-grid";
  for (const [name, caption, alt] of [
    ["motion", "RGB INTERACTION", `${instances[id].title} moving in an RGB interaction sequence`],
    ["depth", "COLORIZED DEPTH", `Colorized depth sequence of ${instances[id].title} moving`],
  ]) {
    const figure = document.createElement("figure");
    figure.append(createImage(asset(id, name), alt));
    const label = document.createElement("figcaption");
    label.textContent = caption;
    figure.append(label);
    grid.append(figure);
  }
  dialogContent.append(grid);
}

function renderGeometryTab(id) {
  const layout = document.createElement("div");
  layout.className = "dialog-geometry";
  const viewerWrap = document.createElement("div");
  viewerWrap.className = "viewer-wrap";
  const fallback = createImage(asset(id, "poster"), `${instances[id].title} object preview`);
  fallback.className = "viewer-fallback";
  const viewer = document.createElement("model-viewer");
  viewer.setAttribute("src", `assets/geometry/${id}.glb`);
  viewer.setAttribute("alt", `Rotatable geometry preview of ${instances[id].title}`);
  viewer.setAttribute("camera-controls", "");
  viewer.setAttribute("camera-orbit", "35deg 70deg auto");
  viewer.setAttribute("touch-action", "pan-y");
  viewer.setAttribute("shadow-intensity", "0.7");
  viewer.setAttribute("exposure", "1.1");
  viewer.addEventListener("load", () => viewerWrap.classList.add("is-ready"));
  viewer.addEventListener("error", () => viewerWrap.classList.add("has-error"));
  viewerWrap.append(fallback, viewer);
  const info = document.createElement("aside");
  info.className = "geometry-note";
  info.innerHTML = '<span class="geometry-symbol" aria-hidden="true">✳</span><h3>Explore the shape</h3><p>Drag to rotate and scroll to zoom. This lightweight preview is derived from the articulated USD geometry; source textures are omitted.</p>';
  layout.append(viewerWrap, info);
  dialogContent.append(layout);
}

function selectTab(tab) {
  if (!currentId || !notes[tab]) return;
  currentTab = tab;
  for (const button of dialogTabs) {
    const selected = button.dataset.tab === tab;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  }
  dialogContent.replaceChildren();
  if (["start", "end", "supplemental"].includes(tab)) renderImageTab(currentId, tab);
  else if (tab === "motion") renderMotionTab(currentId);
  else renderGeometryTab(currentId);
  dialogNote.textContent = notes[tab];
}

function openInstance(id, tab = "start") {
  const instance = instances[id];
  if (!instance) return;
  currentId = id;
  dialogTitle.textContent = instance.title;
  dialogCategory.textContent = `${instance.category.toUpperCase()} / ${id}`;
  dialogCounter.textContent = instance.index;
  selectTab(tab);
  if (!dialog.open) dialog.showModal();
}

document.querySelectorAll(".object-card, [data-open]").forEach((button) => {
  button.addEventListener("click", () => openInstance(button.dataset.id || button.dataset.open, button.dataset.tab || "start"));
});

document.querySelector("#dialog-close").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});
dialog.addEventListener("close", () => {
  dialogContent.replaceChildren();
  currentId = null;
});

dialogTabs.forEach((button, index) => {
  button.addEventListener("click", () => selectTab(button.dataset.tab));
  button.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? dialogTabs.length - 1 :
      (index + (event.key === "ArrowRight" ? 1 : -1) + dialogTabs.length) % dialogTabs.length;
    dialogTabs[next].focus();
    selectTab(dialogTabs[next].dataset.tab);
  });
});

document.querySelectorAll(".filter-button").forEach((button) => {
  button.addEventListener("click", () => {
    const filter = button.dataset.filter;
    document.querySelectorAll(".filter-button").forEach((item) => {
      const active = item === button;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll(".object-card").forEach((card) => {
      card.hidden = filter !== "all" && card.dataset.group !== filter;
    });
  });
});

if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  document.querySelectorAll(".animated-preview").forEach((image) => { image.src = image.dataset.still; });
}
