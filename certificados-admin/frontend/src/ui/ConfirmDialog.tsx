/**
 * ConfirmDialog — accessible confirmation for critical actions.
 *
 * Used for revoking a certificate, activating a template version, and changing
 * a user's access. Three rules it enforces so these never regress:
 *
 *  1. The confirm button names the action ("Revogar certificado"), never "OK" —
 *     a screen-reader user tabbing to it hears what will happen.
 *  2. Destructive dialogs do not close on a backdrop click.
 *  3. When `requireTyped` is set, the operator must type an exact phrase before
 *     confirming, reserved for actions that affect every future certificate.
 */
import { ReactNode, useEffect, useRef, useState } from "react";
import AccessibleModal from "../components/AccessibleModal";
import Button from "./Button";
import { Field, TextInput } from "./Field";
import Alert from "./Alert";

export default function ConfirmDialog({
  open,
  title,
  description,
  children,
  confirmLabel,
  cancelLabel = "Cancelar",
  tone = "danger",
  busy = false,
  error,
  requireTyped,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  description?: string;
  children?: ReactNode;
  /** Names the action, e.g. "Ativar versão 4". */
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "danger" | "primary";
  busy?: boolean;
  error?: string;
  /** Exact phrase the operator must type to enable confirmation. */
  requireTyped?: string;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const cancelRef = useRef<HTMLButtonElement>(null);

  // Reset the typed guard whenever the dialog is reopened.
  useEffect(() => {
    if (open) setTyped("");
  }, [open]);

  const typedOk = !requireTyped || typed.trim() === requireTyped;

  return (
    <AccessibleModal
      open={open}
      title={title}
      description={description}
      onClose={onClose}
      dismissOnBackdrop={false}
      initialFocusRef={cancelRef}
      footer={
        <>
          <Button ref={cancelRef} variant="secondary" onClick={onClose} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            variant={tone === "danger" ? "danger" : "primary"}
            onClick={onConfirm}
            loading={busy}
            disabled={!typedOk}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}

      {requireTyped && (
        <Field
          label={`Digite “${requireTyped}” para confirmar`}
          hint="Confirmação explícita exigida porque esta ação afeta todos os certificados emitidos a partir de agora."
          className="mt-4"
        >
          {(props) => (
            <TextInput
              {...props}
              value={typed}
              autoComplete="off"
              onChange={(event) => setTyped(event.target.value)}
            />
          )}
        </Field>
      )}

      {error && (
        <Alert tone="danger" className="mt-4">
          {error}
        </Alert>
      )}
    </AccessibleModal>
  );
}
