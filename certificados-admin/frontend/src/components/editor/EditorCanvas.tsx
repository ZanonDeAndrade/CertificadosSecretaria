/**
 * Canvas stage.
 *
 * The neutral grey ground is intentional: it separates the certificate's white
 * paper from the application chrome, the way a print preview does, so the
 * operator can see the actual page edge.
 *
 * The page is always shown whole: `stageRef` hands the inner area to the
 * canvas hook, which observes its size and fits the page into it. There is no
 * scrolling here; whatever the window, the panels or the art, the whole
 * certificate is what the operator sees.
 */
import React from "react";
import Icon from "../../ui/Icon";

interface EditorCanvasProps {
  canvasRef: React.Ref<HTMLCanvasElement>;
  stageRef: React.Ref<HTMLDivElement>;
  backgroundUrl: string | null;
}

export default function EditorCanvas({ canvasRef, stageRef, backgroundUrl }: EditorCanvasProps) {
  return (
    <div className="flex min-w-0 flex-1 flex-col bg-[var(--neutral-300)]">
      {!backgroundUrl && (
        <div className="mx-auto mt-4 flex max-w-md shrink-0 flex-col items-center gap-2 rounded-[var(--radius-md)] border border-dashed border-[color:var(--neutral-500)] bg-[var(--neutral-100)] px-6 py-5 text-center">
          <Icon name="image" size={22} className="text-[color:var(--ink-muted)]" />
          <p className="text-[length:var(--text-sm)] font-medium text-[color:var(--ink)]">
            Envie a arte de fundo do certificado
          </p>
          <p className="text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
            Use “Arte de fundo” na barra acima. É a imagem sobre a qual os campos
            serão posicionados.
          </p>
        </div>
      )}

      <div
        ref={stageRef}
        data-testid="editor-stage"
        className="flex min-h-0 min-w-0 flex-1 items-center justify-center overflow-hidden"
      >
        <canvas
          ref={canvasRef}
          className="block shadow-[var(--shadow-lg)]"
          style={{ cursor: "default" }}
        />
      </div>
    </div>
  );
}
