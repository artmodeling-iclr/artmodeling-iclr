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
let physicsDataPromise = null;

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

function loadPhysicsData() {
  if (!physicsDataPromise) {
    physicsDataPromise = fetch("assets/physics.json?v=20261110-physics1").then((response) => {
      if (!response.ok) throw new Error("Physical properties could not be loaded");
      return response.json();
    });
  }
  return physicsDataPromise;
}

function physicalNumber(value, decimals = 5) {
  return Number(Number(value).toPrecision(3)).toLocaleString("en-US", {
    maximumFractionDigits: decimals,
  });
}

function physicsTable(title, columns, rows) {
  const section = document.createElement("section");
  section.className = "physics-group";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const wrapper = document.createElement("div");
  wrapper.className = "physics-table-wrap";
  const table = document.createElement("table");
  table.className = "physics-table";
  const head = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const [label] of columns) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    headerRow.append(cell);
  }
  head.append(headerRow);
  const body = document.createElement("tbody");
  for (const row of rows) {
    const tableRow = document.createElement("tr");
    for (const [label, key, format] of columns) {
      const cell = document.createElement("td");
      cell.dataset.label = label;
      cell.textContent = format ? format(row[key]) : String(row[key]);
      tableRow.append(cell);
    }
    body.append(tableRow);
  }
  table.append(head, body);
  wrapper.append(table);
  section.append(heading, wrapper);
  return section;
}

async function renderPhysicsTab(id) {
  const panel = document.createElement("div");
  panel.className = "dialog-physics";
  const note = document.createElement("p");
  note.className = "physics-note";
  note.textContent = "Estimated values";
  panel.append(note);
  dialogContent.append(panel);

  try {
    const all = await loadPhysicsData();
    if (!panel.isConnected || currentId !== id || currentTab !== "physics") return;
    const values = all[id];
    if (!values) throw new Error("Missing physical properties");
    panel.append(
      physicsTable("Rigid Body Properties", [
        ["Mass (kg)", "mass_kg", (value) => physicalNumber(value)],
        ["Density (kg/m³)", "density_kg_m3", (value) => physicalNumber(value, 0)],
        ["Static friction", "static_friction", (value) => physicalNumber(value)],
        ["Dynamic friction", "dynamic_friction", (value) => physicalNumber(value)],
        ["Material", "material_label"],
      ], values.rigid_bodies),
      physicsTable("Joint Drives", [
        ["Stiffness", "stiffness", (value) => physicalNumber(value)],
        ["Damping", "damping", (value) => physicalNumber(value)],
      ], values.joint_drives),
    );
  } catch {
    if (panel.isConnected && currentId === id && currentTab === "physics") {
      note.textContent = "Physical properties are unavailable.";
    }
  }
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
  dialogContent.scrollTop = 0;
  if (["start", "end", "supplemental"].includes(tab)) renderImageTab(currentId, tab);
  else if (tab === "motion") renderMotionTab(currentId);
  else if (tab === "geometry") renderGeometryTab(currentId);
  else if (tab === "physics") renderPhysicsTab(currentId);
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
