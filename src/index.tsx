import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  TextField,
  staticClasses,
  Focusable,
  DialogButton,
  showModal,
} from "@decky/ui";
import {
  addEventListener,
  removeEventListener,
  callable,
  definePlugin,
  toaster,
} from "@decky/api";
import { useEffect, useState } from "react";
import { FaSave } from "react-icons/fa";

interface Snapshot {
  id: string;
  name: string;
  created: string;
  size: string;
}

interface Game {
  id: string;
  name: string;
  source: string;
  enabled: boolean;
  paths: string[];
  resolved_paths: string[];
}

const getSettings = callable<[], any>("get_settings");
const setSettings = callable<[any], boolean>("set_settings");
const getCredentialsStatus = callable<[], { authenticated: boolean; email?: string }>("get_credentials_status");
const getCredentials = callable<[], { client_id: string; client_secret: string }>("get_credentials");
const startOAuth = callable<[], { verification_url: string; user_code: string; expires_in: number }>("start_oauth");
const logout = callable<[], boolean>("logout");
const getGames = callable<[], Game[]>("get_games");
const setGameEnabled = callable<[string, boolean], boolean>("set_game_enabled");
const setGamePaths = callable<[string, string[]], boolean>("set_game_paths");
const backupNow = callable<[], any[]>("backup_now");
const listSnapshots = callable<[string], Snapshot[]>("list_snapshots");
const restoreSnapshot = callable<[string, string], any>("restore_snapshot");

function OAuthCodeModal({ url, code, onClose }: { url: string; code: string; onClose: () => void }) {
  return (
    <div style={{ padding: 20, minWidth: 300 }}>
      <div className={staticClasses.Title} style={{ marginBottom: 12 }}>Sign in with Google</div>
      <div style={{ fontSize: "0.9em", marginBottom: 12 }}>
        On your phone/PC open:
      </div>
      <div style={{ fontSize: "1.1em", fontWeight: "bold", marginBottom: 12, wordBreak: "break-all" }}>
        {url}
      </div>
      <div style={{ fontSize: "0.9em", marginBottom: 8 }}>Enter this code:</div>
      <div
        style={{
          fontSize: "2em",
          fontWeight: "bold",
          letterSpacing: 4,
          textAlign: "center",
          padding: 12,
          background: "#1a1a1a",
          borderRadius: 8,
          marginBottom: 16,
        }}
      >
        {code}
      </div>
      <DialogButton onClick={onClose}>Close</DialogButton>
    </div>
  );
}

function AuthSection() {
  const [status, setStatus] = useState<{ authenticated: boolean; email?: string } | null>(null);
  const [hasCreds, setHasCreds] = useState(false);

  const refresh = async () => {
    const s = await getCredentialsStatus();
    setStatus(s);
    const c = await getCredentials();
    setHasCreds(Boolean(c.client_id && c.client_secret));
  };

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    const listener = addEventListener("oauth_complete", (ev: any) => {
      if (ev.success) {
        toaster.toast({ title: "Save Drive", body: "Google login completed" });
        refresh();
      } else {
        toaster.toast({ title: "Save Drive", body: `Login failed: ${ev.error || "unknown"}` });
      }
    });
    return () => removeEventListener("oauth_complete", listener);
  }, []);

  return (
    <PanelSection title="Google Drive">
      <PanelSectionRow>
        {status?.authenticated ? (
          <div style={{ fontSize: "0.9em", padding: "6px 0" }}>
            Logged in as {status.email || "Google account"}
          </div>
        ) : (
          <div style={{ fontSize: "0.85em", padding: "6px 0", color: "#aaa" }}>
            {hasCreds
              ? "Credentials loaded. Click Sign in to connect Google Drive."
              : "Credentials not found. See GOOGLE-SETUP.md."}
          </div>
        )}
      </PanelSectionRow>
      {!status?.authenticated && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={!hasCreds}
            onClick={async () => {
              try {
                const info = await startOAuth();
                showModal(
                  <OAuthCodeModal
                    url={info.verification_url}
                    code={info.user_code}
                    onClose={() => {}}
                  />
                );
                toaster.toast({ title: "Save Drive", body: `Code: ${info.user_code}` });
              } catch (e: any) {
                toaster.toast({ title: "Save Drive", body: `OAuth error: ${e.message || e}` });
              }
            }}
          >
            Sign in with Google
          </ButtonItem>
        </PanelSectionRow>
      )}
      {status?.authenticated && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={async () => {
              await logout();
              refresh();
            }}
          >
            Log out
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

function GameRow({ game, onChange }: { game: Game; onChange: () => void }) {
  const [pathsText, setPathsText] = useState(game.paths.join(", "));

  const savePaths = async () => {
    const paths = pathsText.split(",").map((p) => p.trim()).filter(Boolean);
    await setGamePaths(game.id, paths);
    onChange();
  };

  const openSnapshots = async () => {
    const snaps = await listSnapshots(game.id);
    showModal(
      <SnapshotsModal
        game={game}
        snapshots={snaps}
        onClose={() => {}}
      />
    );
  };

  return (
    <PanelSectionRow>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "6px 0" }}>
        <ToggleField
          label={game.name}
          checked={game.enabled}
          onChange={async (checked) => {
            await setGameEnabled(game.id, checked);
            onChange();
          }}
        />
        <div style={{ fontSize: "0.75em", color: "#888" }}>
          {game.resolved_paths.length ? game.resolved_paths.join(" • ") : "No save paths found"}
        </div>
        <TextField
          label="Save paths (comma separated)"
          value={pathsText}
          onChange={(e) => setPathsText(e.target.value)}
        />
        <Focusable style={{ display: "flex", gap: 8 }}>
          <DialogButton onClick={savePaths}>Save paths</DialogButton>
          <DialogButton onClick={openSnapshots}>Snapshots</DialogButton>
        </Focusable>
      </div>
    </PanelSectionRow>
  );
}

function SnapshotsModal({
  game,
  snapshots,
  onClose,
}: {
  game: Game;
  snapshots: Snapshot[];
  onClose: () => void;
}) {
  const [items, setItems] = useState<Snapshot[]>(snapshots);
  const [restoring, setRestoring] = useState<string | null>(null);

  const refresh = async () => setItems(await listSnapshots(game.id));

  return (
    <div style={{ padding: 12 }}>
      <div className={staticClasses.Title}>{game.name} snapshots</div>
      {items.length === 0 && <div>No snapshots found</div>}
      {items.map((s) => (
        <PanelSectionRow key={s.id}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ fontSize: "0.85em" }}>
              {s.name} ({Math.round(Number(s.size || 0) / 1024)} KB)
            </div>
            <DialogButton
              disabled={restoring === s.id}
              onClick={async () => {
                setRestoring(s.id);
                try {
                  await restoreSnapshot(game.id, s.id);
                  toaster.toast({ title: "Save Drive", body: `${game.name} restored` });
                  onClose();
                } catch (e: any) {
                  toaster.toast({ title: "Save Drive", body: `Restore failed: ${e.message || e}` });
                }
                setRestoring(null);
              }}
            >
              Restore
            </DialogButton>
          </div>
        </PanelSectionRow>
      ))}
      <PanelSectionRow>
        <Focusable style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <DialogButton onClick={refresh}>Refresh</DialogButton>
          <DialogButton onClick={onClose}>Close</DialogButton>
        </Focusable>
      </PanelSectionRow>
    </div>
  );
}

function GamesSection() {
  const [games, setGames] = useState<Game[]>([]);

  const refresh = async () => setGames(await getGames());

  useEffect(() => {
    refresh();
  }, []);

  return (
    <PanelSection title="Games">
      {games.map((g) => (
        <GameRow key={g.id} game={g} onChange={refresh} />
      ))}
    </PanelSection>
  );
}

function ConfigSection() {
  const [settings, setLocalSettings] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getSettings().then(setLocalSettings);
  }, []);

  if (!settings) return null;

  const update = (key: string, value: any) => {
    const next = { ...settings, [key]: value };
    setLocalSettings(next);
    setSettings(next);
  };

  return (
    <PanelSection title="Settings">
      <PanelSectionRow>
        <TextField
          label="Snapshots to keep"
          value={String(settings.retention_count)}
          onChange={(e) => update("retention_count", Number(e.target.value))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <TextField
          label="Min hours between backups"
          value={String(settings.min_interval_hours)}
          onChange={(e) => update("min_interval_hours", Number(e.target.value))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const results = await backupNow();
              const ok = results.filter((r) => r.status === "ok").length;
              const up = results.filter((r) => r.status === "up_to_date").length;
              toaster.toast({ title: "Save Drive", body: `Backup done: ${ok} uploaded, ${up} up to date` });
            } catch (e: any) {
              toaster.toast({ title: "Save Drive", body: `Backup failed: ${e.message || e}` });
            }
            setBusy(false);
          }}
        >
          {busy ? "Backing up..." : "Backup now"}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

function Content() {
  return (
    <>
      <AuthSection />
      <ConfigSection />
      <GamesSection />
    </>
  );
}

export default definePlugin(() => {
  return {
    name: "Save Drive",
    titleView: <div className={staticClasses.Title}>Save Drive</div>,
    content: <Content />,
    icon: <FaSave />,
    onDismount() {
      console.log("Save Drive unloading");
    },
  };
});
