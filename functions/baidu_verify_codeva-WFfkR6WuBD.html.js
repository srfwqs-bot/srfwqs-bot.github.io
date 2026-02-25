export function onRequestGet() {
  return new Response("eaff1057e91c26ca6b97deb73526cf5c", {
    status: 200,
    headers: {
      "content-type": "text/html; charset=UTF-8",
      "cache-control": "public, max-age=300",
    },
  });
}
