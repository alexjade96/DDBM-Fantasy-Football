# Low-level Sleeper API access --------------------------------------------

#' Call the public Sleeper API
#'
#' Thin wrapper over the Sleeper v1 REST API with a timeout and retry/backoff,
#' returning parsed JSON. This is the single network entry point used by every
#' other function in the package.
#'
#' @param path API path beginning with `/`, e.g. `"/league/123"` or
#'   `"/league/123/matchups/1"`.
#' @param simplify Passed to [httr2::resp_body_json()] as `simplifyDataFrame`;
#'   `TRUE` (default) returns data frames where possible.
#' @return Parsed response (list or data frame).
#' @seealso [sl_league()], [sl_league_chain()], [sl_season()]
#' @examples
#' \dontrun{
#' state <- sleeper_api("/state/nfl")
#' }
#' @export
sleeper_api <- function(path, simplify = TRUE) {
  httr2::request(paste0("https://api.sleeper.app/v1", path)) %>%
    httr2::req_timeout(30) %>%
    httr2::req_retry(max_tries = 4, retry_on_failure = TRUE, backoff = ~ 2 ^ .x) %>%
    httr2::req_perform() %>%
    httr2::resp_body_json(simplifyDataFrame = simplify)
}
