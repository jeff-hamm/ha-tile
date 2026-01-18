/**
 * Tile Tracker Card - Lovelace card for Tile device trackers
 * 
 * Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
 * Developed with assistance from Claude (Anthropic)
 * 
 * SPDX-License-Identifier: MIT
 */

import {
  CSSResultGroup,
  LitElement,
  PropertyValues,
  TemplateResult,
  css,
  html,
  nothing,
} from "lit";
import { customElement, property, state } from "lit/decorators.js";
import {
  ActionHandlerEvent,
  HomeAssistant,
  LovelaceCard,
  LovelaceCardConfig,
  LovelaceCardEditor,
  fireEvent,
  handleAction,
  hasAction,
} from "custom-card-helpers";

// Card version
const CARD_VERSION = "1.0.0";

// Log card info on load
console.info(
  `%c TILE-TRACKER-CARD %c ${CARD_VERSION} `,
  "color: white; font-weight: bold; background: #1E88E5",
  "color: #1E88E5; font-weight: bold; background: white"
);

// Ring state colors
const RING_STATE_COLORS: Record<string, string> = {
  ringing: "#4CAF50",  // Green - actively ringing
  silent: "#9E9E9E",   // Gray - not ringing
  unknown: "#FF9800",  // Orange - unknown state
};

// Battery level colors
const BATTERY_COLORS = {
  high: "#4CAF50",    // Green (>= 60%)
  medium: "#FF9800",  // Orange (30-59%)
  low: "#F44336",     // Red (< 30%)
};

// Battery icons by level
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

// Card configuration interface
export interface TileTrackerCardConfig extends LovelaceCardConfig {
  type: string;
  entity: string;
  name?: string;
  show_map?: boolean;
  map_height?: number;
  show_attributes?: string[];
  tap_action?: ActionConfig;
  hold_action?: ActionConfig;
  double_tap_action?: ActionConfig;
}

interface ActionConfig {
  action: string;
  navigation_path?: string;
  service?: string;
  service_data?: Record<string, unknown>;
}

// Default attributes to show
const DEFAULT_ATTRIBUTES = [
  "last_seen",
  "latitude",
  "longitude",
  "source_type",
];

// Register card with Home Assistant
(window as unknown as { customCards: unknown[] }).customCards =
  (window as unknown as { customCards: unknown[] }).customCards || [];
(window as unknown as { customCards: unknown[] }).customCards.push({
  type: "tile-tracker-card",
  name: "Tile Tracker Card",
  description: "A card for displaying Tile device trackers with ring control",
});

@customElement("tile-tracker-card")
export class TileTrackerCard extends LitElement implements LovelaceCard {
  @property({ attribute: false }) public hass!: HomeAssistant;
  @state() private _config!: TileTrackerCardConfig;

  // Get card editor
  public static async getConfigElement(): Promise<LovelaceCardEditor> {
    await import("./tile-tracker-card-editor");
    return document.createElement("tile-tracker-card-editor") as LovelaceCardEditor;
  }

  // Stub config for card picker
  public static getStubConfig(): Record<string, unknown> {
    return {
      type: "custom:tile-tracker-card",
      entity: "",
      show_map: true,
      show_attributes: DEFAULT_ATTRIBUTES,
    };
  }

  // Set card configuration
  public setConfig(config: TileTrackerCardConfig): void {
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
      tap_action: { action: "more-info" },
      ...config,
    };
  }

  // Card size for layout
  public getCardSize(): number {
    let size = 2; // Header
    if (this._config?.show_map) size += 3;
    if (this._config?.show_attributes?.length) {
      size += Math.ceil(this._config.show_attributes.length / 2);
    }
    return size;
  }

  // Should update?
  protected shouldUpdate(changedProps: PropertyValues): boolean {
    if (!this._config) return false;
    if (changedProps.has("_config")) return true;
    if (!changedProps.has("hass")) return false;

    const oldHass = changedProps.get("hass") as HomeAssistant | undefined;
    if (!oldHass) return true;

    const entityId = this._config.entity;
    return oldHass.states[entityId] !== this.hass.states[entityId];
  }

  // Render card
  protected render(): TemplateResult | typeof nothing {
    if (!this._config || !this.hass) {
      return nothing;
    }

    const entityId = this._config.entity;
    const stateObj = this.hass.states[entityId];

    if (!stateObj) {
      return html`
        <ha-card>
          <div class="warning">
            Entity not found: ${entityId}
          </div>
        </ha-card>
      `;
    }

    const name = this._config.name || stateObj.attributes.friendly_name || entityId;
    const product = stateObj.attributes.product || "Tile";
    const ringState = stateObj.attributes.ring_state || "silent";
    const batteryLevel = this._getBatteryLevel(stateObj);
    const batteryStatus = stateObj.attributes.battery_status || "unknown";

    return html`
      <ha-card>
        ${this._renderHeader(name, product, ringState, batteryLevel, batteryStatus)}
        ${this._config.show_map ? this._renderMap(stateObj) : nothing}
        ${this._renderAttributes(stateObj)}
      </ha-card>
    `;
  }

  // Render header row
  private _renderHeader(
    name: string,
    product: string,
    ringState: string,
    batteryLevel: number | null,
    batteryStatus: string
  ): TemplateResult {
    const ringColor = RING_STATE_COLORS[ringState] || RING_STATE_COLORS.unknown;
    const ringIcon = ringState === "ringing" ? "mdi:bell-ring" : "mdi:bell";
    const batteryInfo = this._getBatteryInfo(batteryLevel, batteryStatus);

    return html`
      <div class="header" @click=${this._handleHeaderClick}>
        <div class="info">
          <div class="name">${name}</div>
          <div class="product">${product}</div>
        </div>
        <div class="controls">
          <div
            class="ring-button"
            style="--ring-color: ${ringColor}"
            @click=${this._handleRingClick}
            title="Ring Tile"
          >
            <ha-icon icon="${ringIcon}"></ha-icon>
          </div>
          <div class="battery" title="${batteryInfo.tooltip}">
            <ha-icon
              icon="${batteryInfo.icon}"
              style="color: ${batteryInfo.color}"
            ></ha-icon>
            ${batteryLevel !== null
              ? html`<span class="battery-text">${batteryLevel}%</span>`
              : nothing}
          </div>
        </div>
      </div>
    `;
  }

  // Render map (if lat/lon available)
  private _renderMap(stateObj: { attributes: Record<string, unknown> }): TemplateResult | typeof nothing {
    const lat = stateObj.attributes.latitude as number | undefined;
    const lon = stateObj.attributes.longitude as number | undefined;

    if (!lat || !lon) {
      return html`
        <div class="map-placeholder">
          <ha-icon icon="mdi:map-marker-question"></ha-icon>
          <span>Location unavailable</span>
        </div>
      `;
    }

    // Use HA's built-in map component via iframe
    const mapHeight = this._config.map_height || 150;
    
    return html`
      <div class="map-container" style="height: ${mapHeight}px">
        <ha-map
          .hass=${this.hass}
          .entities=${[{ entity_id: this._config.entity }]}
          .zoom=${15}
          .interactiveZones=${false}
          fitZones
        ></ha-map>
      </div>
    `;
  }

  // Render attributes section
  private _renderAttributes(stateObj: { attributes: Record<string, unknown> }): TemplateResult | typeof nothing {
    const attrs = this._config.show_attributes || [];
    if (!attrs.length) return nothing;

    // Filter to attributes that exist
    const displayAttrs = attrs.filter((attr) => 
      stateObj.attributes[attr] !== undefined
    );

    if (!displayAttrs.length) return nothing;

    return html`
      <div class="divider"></div>
      <div class="attributes">
        ${displayAttrs.map((attr) => this._renderAttribute(attr, stateObj.attributes[attr]))}
      </div>
    `;
  }

  // Render single attribute
  private _renderAttribute(name: string, value: unknown): TemplateResult {
    const displayName = this._formatAttributeName(name);
    const displayValue = this._formatAttributeValue(name, value);

    return html`
      <div class="attribute">
        <div class="attr-name">${displayName}</div>
        <div class="attr-value">${displayValue}</div>
      </div>
    `;
  }

  // Format attribute name for display
  private _formatAttributeName(name: string): string {
    return name
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  }

  // Format attribute value for display
  private _formatAttributeValue(name: string, value: unknown): string {
    if (value === null || value === undefined) return "Unknown";

    // Special formatting for certain attributes
    if (name === "last_seen" && typeof value === "string") {
      try {
        const date = new Date(value);
        return date.toLocaleString();
      } catch {
        return String(value);
      }
    }

    if ((name === "latitude" || name === "longitude") && typeof value === "number") {
      return value.toFixed(6);
    }

    return String(value);
  }

  // Get battery level from state object
  private _getBatteryLevel(stateObj: { attributes: Record<string, unknown> }): number | null {
    const level = stateObj.attributes.battery_level;
    if (typeof level === "number") return level;
    if (typeof level === "string") {
      const parsed = parseInt(level, 10);
      return isNaN(parsed) ? null : parsed;
    }
    return null;
  }

  // Get battery icon and color
  private _getBatteryInfo(
    level: number | null,
    status: string
  ): { icon: string; color: string; tooltip: string } {
    if (level === null) {
      // Use status string
      const statusLower = status.toLowerCase();
      if (statusLower.includes("full") || statusLower.includes("high")) {
        return {
          icon: BATTERY_ICONS.full,
          color: BATTERY_COLORS.high,
          tooltip: `Battery: ${status}`,
        };
      }
      if (statusLower.includes("medium") || statusLower.includes("ok")) {
        return {
          icon: BATTERY_ICONS[50],
          color: BATTERY_COLORS.medium,
          tooltip: `Battery: ${status}`,
        };
      }
      if (statusLower.includes("low")) {
        return {
          icon: BATTERY_ICONS[20],
          color: BATTERY_COLORS.low,
          tooltip: `Battery: ${status}`,
        };
      }
      return {
        icon: BATTERY_ICONS.unknown,
        color: "#9E9E9E",
        tooltip: `Battery: ${status}`,
      };
    }

    // Numeric level
    let icon = BATTERY_ICONS.outline;
    let color = BATTERY_COLORS.low;

    if (level >= 95) {
      icon = BATTERY_ICONS.full;
      color = BATTERY_COLORS.high;
    } else if (level >= 85) {
      icon = BATTERY_ICONS[90];
      color = BATTERY_COLORS.high;
    } else if (level >= 75) {
      icon = BATTERY_ICONS[80];
      color = BATTERY_COLORS.high;
    } else if (level >= 65) {
      icon = BATTERY_ICONS[70];
      color = BATTERY_COLORS.high;
    } else if (level >= 55) {
      icon = BATTERY_ICONS[60];
      color = BATTERY_COLORS.high;
    } else if (level >= 45) {
      icon = BATTERY_ICONS[50];
      color = BATTERY_COLORS.medium;
    } else if (level >= 35) {
      icon = BATTERY_ICONS[40];
      color = BATTERY_COLORS.medium;
    } else if (level >= 25) {
      icon = BATTERY_ICONS[30];
      color: BATTERY_COLORS.medium;
    } else if (level >= 15) {
      icon = BATTERY_ICONS[20];
      color = BATTERY_COLORS.low;
    } else if (level >= 5) {
      icon = BATTERY_ICONS[10];
      color = BATTERY_COLORS.low;
    } else {
      icon = BATTERY_ICONS.outline;
      color = BATTERY_COLORS.low;
    }

    return { icon, color, tooltip: `Battery: ${level}%` };
  }

  // Handle header click
  private _handleHeaderClick(ev: Event): void {
    ev.stopPropagation();
    fireEvent(this, "hass-more-info", { entityId: this._config.entity });
  }

  // Handle ring button click
  private _handleRingClick(ev: Event): void {
    ev.stopPropagation();
    
    // Get tile_id from entity attributes
    const stateObj = this.hass.states[this._config.entity];
    const tileId = stateObj?.attributes?.tile_id;

    if (!tileId) {
      console.error("No tile_id found in entity attributes");
      return;
    }

    // Call the play_sound service
    this.hass.callService("tile_tracker", "play_sound", {
      tile_id: tileId,
      volume: "medium",
      duration: 5,
    });
  }

  // Styles
  static get styles(): CSSResultGroup {
    return css`
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

      .map-container ha-map {
        height: 100%;
        width: 100%;
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

// Declare for TypeScript
declare global {
  interface HTMLElementTagNameMap {
    "tile-tracker-card": TileTrackerCard;
  }
}
