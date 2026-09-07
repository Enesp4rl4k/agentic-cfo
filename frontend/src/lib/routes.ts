/**
 * Where the app sends people.
 *
 * `/` is the marketing landing page. It used to be the dashboard, and when the
 * landing page took the route every default that pointed at `/` quietly became
 * "go and read the pitch". That has now been found three times: after an
 * upload, after signing in, and on a role denial. So the destinations live
 * here, named, instead of being spelled `"/"` in each place that needs one.
 *
 * `(dashboard)` is a route *group* — it is not a URL segment, so there is no
 * `/dashboard` page to fall back to. Every route below is one that exists.
 */

/** First screen of the product for a signed-in user. */
export const APP_HOME = "/command-center";

/** Where an upload lands, carrying its job id. */
export const POST_UPLOAD_ROUTE = "/pnl";

/** Where someone goes when their role does not allow the page they asked for. */
export const ACCESS_DENIED_ROUTE = APP_HOME;
