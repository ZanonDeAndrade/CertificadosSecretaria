import { FormEvent, useEffect, useRef, useState } from "react";
import { changeOwnPassword, getApiErrorMessage } from "../services/api";
import {
  MIN_PASSWORD_LENGTH,
  PASSWORD_POLICY_HINT,
  passwordPolicyError,
} from "../security/passwordPolicy";
import Alert from "../ui/Alert";
import Button from "../ui/Button";
import { Field, TextInput } from "../ui/Field";

export default function PasswordChangeForm({
  onChanged,
  submitLabel = "Alterar senha",
}: {
  onChanged?: (sessionsRevoked: number) => void | Promise<void>;
  submitLabel?: string;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const currentRef = useRef<HTMLInputElement>(null);

  // The controls are disabled while the request is pending. Restore focus only
  // after that state has ended; focusing a disabled input is ignored by the
  // browser and would leave keyboard users stranded on the submit button.
  useEffect(() => {
    if (error && !busy) currentRef.current?.focus();
  }, [error, busy]);

  const newPasswordError = newPassword ? passwordPolicyError(newPassword) : "";
  const confirmationError =
    confirmation.length > 0 && confirmation !== newPassword
      ? "As senhas novas não coincidem."
      : "";
  const valid =
    Boolean(currentPassword) &&
    !newPasswordError &&
    newPassword !== currentPassword &&
    confirmation === newPassword;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await changeOwnPassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
      setSuccess(
        result.sessions_revoked > 0
          ? `Senha alterada. ${result.sessions_revoked} outra(s) sessão(ões) foram encerradas.`
          : "Senha alterada com segurança.",
      );
      await onChanged?.(result.sessions_revoked);
    } catch (requestError) {
      setError(
        getApiErrorMessage(requestError, "Não foi possível alterar a senha."),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Field label="Senha atual" required>
        {(props) => (
          <TextInput
            {...props}
            ref={currentRef}
            type="password"
            value={currentPassword}
            autoComplete="current-password"
            disabled={busy}
            onChange={(event) => setCurrentPassword(event.target.value)}
          />
        )}
      </Field>

      <Field
        label="Nova senha"
        hint={`${PASSWORD_POLICY_HINT} Não reutilize a senha atual.`}
        error={newPasswordError}
        required
      >
        {(props) => (
          <TextInput
            {...props}
            type="password"
            value={newPassword}
            minLength={MIN_PASSWORD_LENGTH}
            autoComplete="new-password"
            disabled={busy}
            onChange={(event) => setNewPassword(event.target.value)}
          />
        )}
      </Field>

      <Field label="Confirmar nova senha" error={confirmationError} required>
        {(props) => (
          <TextInput
            {...props}
            type="password"
            value={confirmation}
            minLength={MIN_PASSWORD_LENGTH}
            autoComplete="new-password"
            disabled={busy}
            onChange={(event) => setConfirmation(event.target.value)}
          />
        )}
      </Field>

      {newPassword && newPassword === currentPassword && (
        <Alert tone="warn">A nova senha precisa ser diferente da atual.</Alert>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      {success && <Alert tone="ok">{success}</Alert>}

      <Button
        type="submit"
        variant="primary"
        loading={busy}
        disabled={!valid}
      >
        {busy ? "Alterando…" : submitLabel}
      </Button>
    </form>
  );
}
