import type { BlockProps } from "./kit";
import { EmptyState } from "./kit";

type GalleryItem = {
  object_uid?: string;
  title?: string;
  attachment?: {
    url?: string;
    filename?: string | null;
    content_type?: string | null;
    size?: number;
  };
};

export function Gallery({ data, onOpenDetail }: BlockProps) {
  const items = (Array.isArray(data.items) ? data.items : []) as GalleryItem[];
  const objectType = String(data.object_type ?? "");
  if (items.length === 0) {
    return <EmptyState title="No media yet" hint="Attach a photo while capturing a record and it will appear here." />;
  }
  return (
    <div className="media-gallery" data-testid="media-gallery">
      {items.map((item, index) => {
        const uid = item.object_uid;
        return (
          <figure className="media-tile" key={`${uid ?? "media"}-${index}`}>
            {item.attachment?.url ? (
              <img src={item.attachment.url} alt={item.attachment.filename ?? item.title ?? "Attached media"} />
            ) : (
              <div className="media-missing" role="img" aria-label="Attachment unavailable">Media unavailable</div>
            )}
            <figcaption>
              {uid && onOpenDetail ? (
                <button type="button" className="detail-link" onClick={() => onOpenDetail(objectType, uid)}>
                  {item.title ?? uid}
                </button>
              ) : <span>{item.title ?? "Attached media"}</span>}
              {item.attachment?.filename && <span className="muted">{item.attachment.filename}</span>}
            </figcaption>
          </figure>
        );
      })}
    </div>
  );
}
