/**
 * Canvas stage.
 *
 * The neutral grey ground is intentional: it separates the certificate's white
 * paper from the application chrome, the way a print preview does, so the
 * operator can see the actual page edge.
 *
 * Zoom scales a wrapper rather than the fabric canvas itself, which keeps
 * fabric's own coordinate space (and therefore hit-testing) untouched.
 */
import React from "react";
import Icon from "../../ui/Icon";

interface EditorCanvasProps {
  canvasRef: React.Ref<HTMLCanvasElement>;
  backgroundUrl: string | null;
  zoom: number;
}

export default function EditorCanvas({
  canvasRef,
  backgroundUrl,
  zoom,
}: EditorCanvasProps) {
  return (
    <div className="flex min-w-0 flex-1 flex-col items-center overflow-auto bg-[var(--neutral-300)] p-4 sm:p-6">
      {!backgroundUrl && (
        <div className="mb-4 flex max-w-md flex-col items-center gap-2 rounded-[var(--radius-md)] border border-dashed border-[color:var(--neutral-500)] bg-[var(--neutral-100)] px-6 py-5 text-center">
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
        style={{
          transform: `scale(${zoom})`,
          transformOrigin: "top center",
        }}
        className="motion-safe:transition-transform motion-safe:duration-150"
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
