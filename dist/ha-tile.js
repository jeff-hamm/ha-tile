/**
 * Tile Tracker Card v1.0.0
 * 
 * A Lovelace card for displaying Tile device trackers with ring control.
 * 
 * Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
 * Developed with assistance from Claude (Anthropic)
 * 
 * SPDX-License-Identifier: MIT
 */

const CARD_VERSION = "1.0.0";

console.info(
  `%c TILE-TRACKER-CARD %c ${CARD_VERSION} `,
  "color: white; font-weight: bold; background: #1E88E5",
  "color: #1E88E5; font-weight: bold; background: white"
);

// Ring state colors
const RING_STATE_COLORS = {
  ringing: "#4CAF50",
  silent: "#9E9E9E",
  unknown: "#FF9800",
};

// Battery colors
const BATTERY_COLORS = {
  high: "#4CAF50",
  medium: "#FF9800",
  low: "#F44336",
};

// Battery icons
const BATTERY_ICONS = {
  full: "mdi:battery",
  90: "mdi:battery-90",
  80: "mdi:battery-80",
  70: "mdi:battery-70",
  60: "mdi:battery-60",
  50: "mdi:battery-50",
  40: "mdi:battery-40",
  30: "mdi:battery-30",
  20: "mdi:battery-20",
  10: "mdi:battery-10",
  outline: "mdi:battery-outline",
  unknown: "mdi:battery-unknown",
};

// Default attributes
const DEFAULT_ATTRIBUTES = ["last_seen", "latitude", "longitude", "source_type"];

// Available attributes for editor
const AVAILABLE_ATTRIBUTES = [
  { value: "last_seen", label: "Last Seen" },
  { value: "latitude", label: "Latitude" },
  { value: "longitude", label: "Longitude" },
  { value: "source_type", label: "Source Type" },
  { value: "tile_id", label: "Tile ID" },
  { value: "battery_status", label: "Battery Status" },
  { value: "ring_state", label: "Ring State" },
  { value: "voip_state", label: "VoIP State" },
  { value: "firmware_version", label: "Firmware Version" },
  { value: "hardware_version", label: "Hardware Version" },
];

// Register card
window.customCards = window.customCards || [];
window.customCards.push({
  type: "tile-tracker-card",
  name: "Tile Tracker Card",
  description: "A card for displaying Tile device trackers with ring control",
  preview: true,
});

// Card class
class TileTrackerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
  }

  static getConfigElement() {
    return document.createElement("tile-tracker-card-editor");
  }

  static getStubConfig() {
    return {
      type: "custom:tile-tracker-card",
      entity: "",
      show_map: true,
      show_attributes: DEFAULT_ATTRIBUTES,
    };
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;

    // Only update if entity changed
    if (this._config.entity) {
      const oldState = oldHass?.states?.[this._config.entity];
      const newState = hass.states?.[this._config.entity];
      if (oldState !== newState) {
        this._render();
      }
    }
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("You must specify an entity");
    }
    if (!config.entity.startsWith("device_tracker.")) {
      throw new Error("Entity must be a device_tracker");
    }

    this._config = {
      show_map: true,
      map_height: 150,
      show_attributes: DEFAULT_ATTRIBUTES,
      ...config,
    };

    this._render();
  }

  getCardSize() {
    let size = 2;
    if (this._config.show_map) size += 3;
    if (this._config.show_attributes?.length) {
      size += Math.ceil(this._config.show_attributes.length / 2);
    }
    return size;
  }

  _render() {
    if (!this._hass || !this._config) return;

    const entityId = this._config.entity;
    const stateObj = this._hass.states[entityId];

    if (!stateObj) {
      this.shadowRoot.innerHTML = `
        <ha-card>
          <style>${this._getStyles()}</style>
          <div class="warning">Entity not found: ${entityId}</div>
        </ha-card>
      `;
      return;
    }

    const name = this._config.name || stateObj.attributes.friendly_name || entityId;
    const product = stateObj.attributes.product || "Tile";
    const ringState = stateObj.attributes.ring_state || "silent";
    const batteryLevel = this._getBatteryLevel(stateObj);
    const batteryStatus = stateObj.attributes.battery_status || "unknown";
    const batteryInfo = this._getBatteryInfo(batteryLevel, batteryStatus);
    const ringColor = RING_STATE_COLORS[ringState] || RING_STATE_COLORS.unknown;
    const ringIcon = ringState === "ringing" ? "mdi:bell-ring" : "mdi:bell";

    this.shadowRoot.innerHTML = `
      <ha-card>
        <style>${this._getStyles()}</style>
        
        <!-- Header -->
        <div class="header" id="header">
          <div class="info">
            <div class="name">${name}</div>
            <div class="product">${product}</div>
          </div>
          <div class="controls">
            <div class="ring-button" id="ring-btn" style="--ring-color: ${ringColor}" title="Ring Tile">
              <ha-icon icon="${ringIcon}"></ha-icon>
            </div>
            <div class="battery" title="${batteryInfo.tooltip}">
              <ha-icon icon="${batteryInfo.icon}" style="color: ${batteryInfo.color}"></ha-icon>
              ${batteryLevel !== null ? `<span class="battery-text">${batteryLevel}%</span>` : ""}
            </div>
          </div>
        </div>

        <!-- Map -->
        ${this._config.show_map ? this._renderMap(stateObj) : ""}

        <!-- Attributes -->
        ${this._renderAttributes(stateObj)}
      </ha-card>
    `;

    // Add event listeners
    this.shadowRoot.getElementById("header")?.addEventListener("click", () => this._handleHeaderClick());
    this.shadowRoot.getElementById("ring-btn")?.addEventListener("click", (e) => this._handleRingClick(e));
  }

  _renderMap(stateObj) {
    const lat = stateObj.attributes.latitude;
    const lon = stateObj.attributes.longitude;
    const height = this._config.map_height || 150;

    if (!lat || !lon) {
      return `
        <div class="map-placeholder">
          <ha-icon icon="mdi:map-marker-question"></ha-icon>
          <span>Location unavailable</span>
        </div>
      `;
    }

    // Use OpenStreetMap static tile as fallback (ha-map requires more setup)
    const zoom = 15;
    const mapUrl = `https://www.openstreetmap.org/export/embed.html?bbox=${lon - 0.005}%2C${lat - 0.005}%2C${lon + 0.005}%2C${lat + 0.005}&layer=mapnik&marker=${lat}%2C${lon}`;

    return `
      <div class="map-container" style="height: ${height}px">
        <iframe
          src="${mapUrl}"
          style="border: 0; width: 100%; height: 100%;"
          loading="lazy"
        ></iframe>
      </div>
    `;
  }

  _renderAttributes(stateObj) {
    const attrs = this._config.show_attributes || [];
    if (!attrs.length) return "";

    const displayAttrs = attrs.filter((attr) => stateObj.attributes[attr] !== undefined);
    if (!displayAttrs.length) return "";

    const attrHtml = displayAttrs
      .map((attr) => {
        const displayName = attr.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
        let value = stateObj.attributes[attr];

        // Format special values
        if (attr === "last_seen" && value) {
          try {
            value = new Date(value).toLocaleString();
          } catch {}
        } else if ((attr === "latitude" || attr === "longitude") && typeof value === "number") {
          value = value.toFixed(6);
        }

        return `
          <div class="attribute">
            <div class="attr-name">${displayName}</div>
            <div class="attr-value">${value ?? "Unknown"}</div>
          </div>
        `;
      })
      .join("");

    return `
      <div class="divider"></div>
      <div class="attributes">${attrHtml}</div>
    `;
  }

  _getBatteryLevel(stateObj) {
    const level = stateObj.attributes.battery_level;
    if (typeof level === "number") return level;
    if (typeof level === "string") {
      const parsed = parseInt(level, 10);
      return isNaN(parsed) ? null : parsed;
    }
    return null;
  }

  _getBatteryInfo(level, status) {
    if (level === null) {
      const s = status.toLowerCase();
      if (s.includes("full") || s.includes("high")) {
        return { icon: BATTERY_ICONS.full, color: BATTERY_COLORS.high, tooltip: `Battery: ${status}` };
      }
      if (s.includes("medium") || s.includes("ok")) {
        return { icon: BATTERY_ICONS[50], color: BATTERY_COLORS.medium, tooltip: `Battery: ${status}` };
      }
      if (s.includes("low")) {
        return { icon: BATTERY_ICONS[20], color: BATTERY_COLORS.low, tooltip: `Battery: ${status}` };
      }
      return { icon: BATTERY_ICONS.unknown, color: "#9E9E9E", tooltip: `Battery: ${status}` };
    }

    let icon = BATTERY_ICONS.outline;
    let color = BATTERY_COLORS.low;

    if (level >= 95) { icon = BATTERY_ICONS.full; color = BATTERY_COLORS.high; }
    else if (level >= 85) { icon = BATTERY_ICONS[90]; color = BATTERY_COLORS.high; }
    else if (level >= 75) { icon = BATTERY_ICONS[80]; color = BATTERY_COLORS.high; }
    else if (level >= 65) { icon = BATTERY_ICONS[70]; color = BATTERY_COLORS.high; }
    else if (level >= 55) { icon = BATTERY_ICONS[60]; color = BATTERY_COLORS.high; }
    else if (level >= 45) { icon = BATTERY_ICONS[50]; color = BATTERY_COLORS.medium; }
    else if (level >= 35) { icon = BATTERY_ICONS[40]; color = BATTERY_COLORS.medium; }
    else if (level >= 25) { icon = BATTERY_ICONS[30]; color = BATTERY_COLORS.medium; }
    else if (level >= 15) { icon = BATTERY_ICONS[20]; color = BATTERY_COLORS.low; }
    else if (level >= 5) { icon = BATTERY_ICONS[10]; color = BATTERY_COLORS.low; }

    return { icon, color, tooltip: `Battery: ${level}%` };
  }

  _handleHeaderClick() {
    const event = new CustomEvent("hass-more-info", {
      bubbles: true,
      composed: true,
      detail: { entityId: this._config.entity },
    });
    this.dispatchEvent(event);
  }

  _handleRingClick(e) {
    e.stopPropagation();

    const stateObj = this._hass.states[this._config.entity];
    const tileId = stateObj?.attributes?.tile_id;

    if (!tileId) {
      console.error("No tile_id found in entity attributes");
      return;
    }

    this._hass.callService("tile_tracker", "play_sound", {
      tile_id: tileId,
      volume: "medium",
      duration: 5,
    });
  }

  _getStyles() {
    return `
      :host {
        display: block;
      }
      ha-card {
        padding: 0;
        overflow: hidden;
      }
      .warning {
        padding: 16px;
        color: var(--warning-color, #ffc107);
        text-align: center;
      }
      .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px;
        cursor: pointer;
      }
      .header:hover {
        background: var(--secondary-background-color);
      }
      .info {
        flex: 1;
        min-width: 0;
      }
      .name {
        font-weight: 500;
        font-size: 1.1em;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .product {
        color: var(--secondary-text-color);
        font-size: 0.9em;
      }
      .controls {
        display: flex;
        align-items: center;
        gap: 12px;
      }
      .ring-button {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: var(--ring-color, #9E9E9E);
        color: white;
        cursor: pointer;
        transition: transform 0.2s, box-shadow 0.2s;
      }
      .ring-button:hover {
        transform: scale(1.1);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
      }
      .ring-button:active {
        transform: scale(0.95);
      }
      .ring-button ha-icon {
        --mdc-icon-size: 24px;
      }
      .battery {
        display: flex;
        align-items: center;
        gap: 4px;
      }
      .battery ha-icon {
        --mdc-icon-size: 24px;
      }
      .battery-text {
        font-size: 0.85em;
        color: var(--secondary-text-color);
      }
      .map-container {
        width: 100%;
        position: relative;
        overflow: hidden;
      }
      .map-placeholder {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100px;
        color: var(--secondary-text-color);
        gap: 8px;
      }
      .map-placeholder ha-icon {
        --mdc-icon-size: 32px;
        opacity: 0.5;
      }
      .divider {
        height: 1px;
        background-color: var(--divider-color);
        margin: 0 16px;
      }
      .attributes {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 8px;
        padding: 12px 16px;
      }
      .attribute {
        display: flex;
        flex-direction: column;
      }
      .attr-name {
        font-size: 0.8em;
        color: var(--secondary-text-color);
        text-transform: capitalize;
      }
      .attr-value {
        font-size: 0.95em;
        word-break: break-word;
      }
      @media (max-width: 400px) {
        .attributes {
          grid-template-columns: 1fr;
        }
      }
    `;
  }
}

// Editor class
class TileTrackerCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  setConfig(config) {
    this._config = config;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;

    const entities = Object.keys(this._hass.states)
      .filter((e) => e.startsWith("device_tracker."))
      .sort();

    const attrCheckboxes = AVAILABLE_ATTRIBUTES.map((attr) => `
      <label class="checkbox-item">
        <input type="checkbox" data-attr="${attr.value}" 
          ${(this._config.show_attributes || []).includes(attr.value) ? "checked" : ""}>
        ${attr.label}
      </label>
    `).join("");

    this.shadowRoot.innerHTML = `
      <style>
        .card-config {
          display: flex;
          flex-direction: column;
          gap: 16px;
          padding: 16px;
        }
        .field {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .field > label {
          font-weight: 500;
          font-size: 0.9em;
        }
        .field.checkbox > label {
          display: flex;
          align-items: center;
          gap: 8px;
          cursor: pointer;
        }
        input[type="text"], input[type="number"], select {
          padding: 8px 12px;
          border: 1px solid var(--divider-color);
          border-radius: 4px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font-size: 1em;
        }
        .checkboxes {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 8px;
        }
        .checkbox-item {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.9em;
          cursor: pointer;
        }
      </style>
      <div class="card-config">
        <div class="field">
          <label>Entity *</label>
          <select id="entity">
            <option value="">Select a device tracker...</option>
            ${entities.map((e) => `
              <option value="${e}" ${this._config.entity === e ? "selected" : ""}>
                ${this._hass.states[e]?.attributes?.friendly_name || e}
              </option>
            `).join("")}
          </select>
        </div>

        <div class="field">
          <label>Name (optional)</label>
          <input type="text" id="name" value="${this._config.name || ""}" placeholder="Override display name">
        </div>

        <div class="field checkbox">
          <label>
            <input type="checkbox" id="show_map" ${this._config.show_map !== false ? "checked" : ""}>
            Show Map
          </label>
        </div>

        <div class="field">
          <label>Map Height (px)</label>
          <input type="number" id="map_height" min="50" max="500" value="${this._config.map_height || 150}">
        </div>

        <div class="field">
          <label>Attributes to Display</label>
          <div class="checkboxes" id="attrs">
            ${attrCheckboxes}
          </div>
        </div>
      </div>
    `;

    // Add event listeners
    this.shadowRoot.getElementById("entity")?.addEventListener("change", (e) => {
      this._updateConfig({ entity: e.target.value });
    });

    this.shadowRoot.getElementById("name")?.addEventListener("input", (e) => {
      const val = e.target.value;
      if (val) {
        this._updateConfig({ name: val });
      } else {
        const newConfig = { ...this._config };
        delete newConfig.name;
        this._config = newConfig;
        this._fireConfigChanged();
      }
    });

    this.shadowRoot.getElementById("show_map")?.addEventListener("change", (e) => {
      this._updateConfig({ show_map: e.target.checked });
    });

    this.shadowRoot.getElementById("map_height")?.addEventListener("input", (e) => {
      const val = parseInt(e.target.value, 10);
      if (!isNaN(val)) this._updateConfig({ map_height: val });
    });

    this.shadowRoot.querySelectorAll("#attrs input[type='checkbox']").forEach((cb) => {
      cb.addEventListener("change", (e) => {
        const attr = e.target.dataset.attr;
        const checked = e.target.checked;
        const current = this._config.show_attributes || [];
        
        let newAttrs;
        if (checked && !current.includes(attr)) {
          newAttrs = [...current, attr];
        } else if (!checked && current.includes(attr)) {
          newAttrs = current.filter((a) => a !== attr);
        } else {
          return;
        }
        
        this._updateConfig({ show_attributes: newAttrs });
      });
    });
  }

  _updateConfig(updates) {
    this._config = { ...this._config, ...updates };
    this._fireConfigChanged();
  }

  _fireConfigChanged() {
    const event = new CustomEvent("config-changed", {
      bubbles: true,
      composed: true,
      detail: { config: this._config },
    });
    this.dispatchEvent(event);
  }
}

// Register elements
customElements.define("tile-tracker-card", TileTrackerCard);
customElements.define("tile-tracker-card-editor", TileTrackerCardEditor);
