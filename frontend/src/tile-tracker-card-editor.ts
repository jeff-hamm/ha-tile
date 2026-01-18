/**
 * Tile Tracker Card Editor - Configuration UI for the card
 * 
 * Copyright (c) 2024-2026 Jeff Hamm <jeff.hamm@gmail.com>
 * Developed with assistance from Claude (Anthropic)
 * 
 * SPDX-License-Identifier: MIT
 */

import { LitElement, html, css, CSSResultGroup, TemplateResult, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { HomeAssistant, LovelaceCardEditor, fireEvent } from "custom-card-helpers";
import { TileTrackerCardConfig } from "./tile-tracker-card";

// Available attributes for selection
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

@customElement("tile-tracker-card-editor")
export class TileTrackerCardEditor extends LitElement implements LovelaceCardEditor {
  @property({ attribute: false }) public hass!: HomeAssistant;
  @state() private _config!: TileTrackerCardConfig;

  // Set config from card
  public setConfig(config: TileTrackerCardConfig): void {
    this._config = config;
  }

  // Get device_tracker entities
  private _getDeviceTrackers(): string[] {
    if (!this.hass) return [];
    
    return Object.keys(this.hass.states)
      .filter((entityId) => entityId.startsWith("device_tracker."))
      .filter((entityId) => {
        const state = this.hass.states[entityId];
        // Filter to only Tile trackers if possible
        return state.attributes?.source === "tile" || 
               state.attributes?.tile_id !== undefined ||
               entityId.toLowerCase().includes("tile");
      })
      .sort();
  }

  // Render editor
  protected render(): TemplateResult {
    if (!this.hass || !this._config) {
      return html``;
    }

    const entities = this._getDeviceTrackers();
    const allTrackers = Object.keys(this.hass.states)
      .filter((e) => e.startsWith("device_tracker."))
      .sort();

    return html`
      <div class="card-config">
        <div class="field">
          <label>Entity *</label>
          <select
            .value=${this._config.entity || ""}
            @change=${this._entityChanged}
          >
            <option value="">Select a Tile tracker...</option>
            ${entities.length > 0 ? html`
              <optgroup label="Tile Trackers">
                ${entities.map((entity) => html`
                  <option value=${entity} ?selected=${this._config.entity === entity}>
                    ${this.hass.states[entity]?.attributes?.friendly_name || entity}
                  </option>
                `)}
              </optgroup>
            ` : nothing}
            ${allTrackers.length > entities.length ? html`
              <optgroup label="Other Device Trackers">
                ${allTrackers
                  .filter((e) => !entities.includes(e))
                  .map((entity) => html`
                    <option value=${entity} ?selected=${this._config.entity === entity}>
                      ${this.hass.states[entity]?.attributes?.friendly_name || entity}
                    </option>
                  `)}
              </optgroup>
            ` : nothing}
          </select>
        </div>

        <div class="field">
          <label>Name (optional)</label>
          <input
            type="text"
            .value=${this._config.name || ""}
            @input=${this._nameChanged}
            placeholder="Override display name"
          />
        </div>

        <div class="field checkbox">
          <label>
            <input
              type="checkbox"
              .checked=${this._config.show_map !== false}
              @change=${this._showMapChanged}
            />
            Show Map
          </label>
        </div>

        ${this._config.show_map !== false ? html`
          <div class="field">
            <label>Map Height (px)</label>
            <input
              type="number"
              min="50"
              max="500"
              .value=${this._config.map_height || 150}
              @input=${this._mapHeightChanged}
            />
          </div>
        ` : nothing}

        <div class="field">
          <label>Attributes to Display</label>
          <div class="checkboxes">
            ${AVAILABLE_ATTRIBUTES.map((attr) => html`
              <label class="checkbox-item">
                <input
                  type="checkbox"
                  .checked=${(this._config.show_attributes || []).includes(attr.value)}
                  @change=${(e: Event) => this._attributeChanged(attr.value, (e.target as HTMLInputElement).checked)}
                />
                ${attr.label}
              </label>
            `)}
          </div>
        </div>
      </div>
    `;
  }

  // Handle entity change
  private _entityChanged(ev: Event): void {
    const value = (ev.target as HTMLSelectElement).value;
    if (value === this._config.entity) return;
    
    this._updateConfig({ entity: value });
  }

  // Handle name change
  private _nameChanged(ev: Event): void {
    const value = (ev.target as HTMLInputElement).value;
    if (value === this._config.name) return;
    
    if (value) {
      this._updateConfig({ name: value });
    } else {
      const newConfig = { ...this._config };
      delete newConfig.name;
      this._config = newConfig;
      fireEvent(this, "config-changed", { config: this._config });
    }
  }

  // Handle show_map change
  private _showMapChanged(ev: Event): void {
    const checked = (ev.target as HTMLInputElement).checked;
    this._updateConfig({ show_map: checked });
  }

  // Handle map_height change
  private _mapHeightChanged(ev: Event): void {
    const value = parseInt((ev.target as HTMLInputElement).value, 10);
    if (isNaN(value) || value === this._config.map_height) return;
    
    this._updateConfig({ map_height: value });
  }

  // Handle attribute toggle
  private _attributeChanged(attr: string, checked: boolean): void {
    const current = this._config.show_attributes || [];
    let newAttrs: string[];

    if (checked && !current.includes(attr)) {
      newAttrs = [...current, attr];
    } else if (!checked && current.includes(attr)) {
      newAttrs = current.filter((a) => a !== attr);
    } else {
      return;
    }

    this._updateConfig({ show_attributes: newAttrs });
  }

  // Update config and fire event
  private _updateConfig(updates: Partial<TileTrackerCardConfig>): void {
    this._config = { ...this._config, ...updates };
    fireEvent(this, "config-changed", { config: this._config });
  }

  // Styles
  static get styles(): CSSResultGroup {
    return css`
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
        color: var(--primary-text-color);
      }

      .field.checkbox > label {
        display: flex;
        align-items: center;
        gap: 8px;
        cursor: pointer;
      }

      input[type="text"],
      input[type="number"],
      select {
        padding: 8px 12px;
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        background: var(--card-background-color);
        color: var(--primary-text-color);
        font-size: 1em;
      }

      input[type="text"]:focus,
      input[type="number"]:focus,
      select:focus {
        outline: none;
        border-color: var(--primary-color);
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

      .checkbox-item input {
        cursor: pointer;
      }

      @media (max-width: 400px) {
        .checkboxes {
          grid-template-columns: 1fr;
        }
      }
    `;
  }
}

// Declare for TypeScript
declare global {
  interface HTMLElementTagNameMap {
    "tile-tracker-card-editor": TileTrackerCardEditor;
  }
}
