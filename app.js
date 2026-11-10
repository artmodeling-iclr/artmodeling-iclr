const instances = {
  letter_tray1: { title: "Letter Tray" },
  cabinet17: { title: "Cabinet" },
  dressing_case2: { title: "Dressing Case" },
  firstkit2: { title: "First Aid Kit" },
  fryer1: { title: "Air Fryer" },
  laptop1: { title: "Laptop" },
  microwave1: { title: "Microwave" },
  oven4: { title: "Oven" },
  ricebucket1: { title: "Rice Bucket" },
};

const dialog = document.querySelector("#instance-dialog");
const dialogContent = document.querySelector("#dialog-content");
const dialogTitle = document.querySelector("#dialog-title");
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
  layout.className = "dialog-usd-motion";
  const video = document.createElement("video");
  video.src = `assets/motion/${id}.mp4?v=20261110-textures3`;
  video.poster = `${asset(id, "poster")}?v=20261110-front2`;
  video.autoplay = true;
  video.loop = true;
  video.muted = true;
  video.playsInline = true;
  video.controls = true;
  video.preload = "metadata";
  video.setAttribute("aria-label", `${instances[id].title} USD articulated asset motion`);
  video.textContent = "Your browser does not support this video.";
  layout.append(video);
  dialogContent.append(layout);
}

function selectTab(tab) {
  if (!currentId || !dialogTabs.some((button) => button.dataset.tab === tab)) return;
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
}

function openInstance(id, tab = "start") {
  const instance = instances[id];
  if (!instance) return;
  currentId = id;
  dialogTitle.textContent = instance.title;
  selectTab(tab);
  if (!dialog.open) dialog.showModal();
}

document.querySelectorAll(".object-card").forEach((button) => {
  button.addEventListener("click", () => openInstance(button.dataset.id));
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

if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  document.querySelectorAll(".animated-preview").forEach((image) => { image.src = image.dataset.still; });
}
