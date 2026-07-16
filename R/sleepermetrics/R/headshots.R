# Player portraits for the charts (mirrors python/sleepermetrics/headshots.py) --
#
# Sleeper hosts a headshot per player id, and a logo per team -- a team defense
# has no face, so it gets its team's logo instead.
#
# Everything here is best-effort by design. Chart rendering must never depend on
# the network being up, so a fetch that fails (offline, 403 for a player with no
# photo, slow CDN) returns NULL and the caller falls back to a plain text label.
# Failures are cached too: a chart with 20 players must not re-attempt 20 dead
# downloads on every redraw.
#
# Set SLEEPERMETRICS_NO_IMAGES=1 to turn portraits off entirely (tests do this,
# so the suite stays network-free).

SL_PLAYER_CDN <- "https://sleepercdn.com/content/nfl/players"
SL_TEAM_CDN   <- "https://sleepercdn.com/images/team_logos/nfl"

# Ids known to have no image -- never retried.
.sl_shot_miss <- new.env(parent = emptyenv())

.sl_cache_dir <- function() {
  # NB on Windows R expands "~" to Documents/, not the user's home -- which would
  # put the R cache somewhere the Python instance never looks. Prefer the real
  # home so both instances share one downloaded set of portraits.
  home <- Sys.getenv("USERPROFILE", unset = "")
  if (!nzchar(home)) home <- Sys.getenv("HOME", unset = path.expand("~"))
  root <- Sys.getenv("SLEEPERMETRICS_CACHE",
                     file.path(home, ".cache", "sleepermetrics"))
  file.path(root, "headshots")
}

.sl_images_off <- function() {
  !Sys.getenv("SLEEPERMETRICS_NO_IMAGES", "") %in% c("", "0")
}

#' Portrait url for a player (or team logo for a team defense)
#' @param player_id Sleeper player id.
#' @param position Player position; `"DEF"` selects the team logo.
#' @return A url string.
#' @export
sl_headshot_url <- function(player_id, position = NULL) {
  pid <- as.character(player_id)
  is_def <- (!is.null(position) && identical(position, "DEF")) ||
    (grepl("^[A-Za-z]+$", pid) && nchar(pid) <= 4)
  if (is_def) paste0(SL_TEAM_CDN, "/", tolower(pid), ".png")
  else paste0(SL_PLAYER_CDN, "/", pid, ".jpg")
}

# Download `url` to the cache once, keyed by `key`. NULL on any failure.
.sl_fetch_image <- function(url, key) {
  if (is.null(url) || is.na(url) || !nzchar(url) || .sl_images_off()) return(NULL)
  if (!is.null(.sl_shot_miss[[key]])) return(NULL)
  dir <- .sl_cache_dir()
  ext <- tools::file_ext(url)
  dest <- file.path(dir, paste0(key, if (nzchar(ext)) paste0(".", ext) else ".png"))
  if (file.exists(dest)) return(dest)
  ok <- tryCatch({
    if (!dir.exists(dir)) dir.create(dir, recursive = TRUE, showWarnings = FALSE)
    tmp <- tempfile()
    resp <- curl::curl_fetch_disk(url, tmp, handle = curl::new_handle(timeout = 6L))
    # A missing image answers 403 with an HTML error page, not a 404, so status
    # alone is not enough -- insist on actually being handed an image.
    if (resp$status_code == 200 && grepl("^image/", resp$type %||% "")) {
      file.rename(tmp, dest); TRUE
    } else FALSE
  }, error = function(e) FALSE)         # offline, timeout, whatever
  if (!isTRUE(ok)) {
    .sl_shot_miss[[key]] <- TRUE        # degrade to text, and stop trying
    return(NULL)
  }
  dest
}

#' Local path to a player's portrait, downloading it once
#'
#' @param player_id Sleeper player id.
#' @param position Player position (`"DEF"` -> team logo).
#' @return Path to a cached image, or `NULL` when there is no image / no network.
#' @export
sl_headshot <- function(player_id, position = NULL) {
  if (is.null(player_id) || is.na(player_id)) return(NULL)
  .sl_fetch_image(sl_headshot_url(player_id, position), as.character(player_id))
}

# The small thumbnail form of a Sleeper avatar url: the full /avatars/<id> is
# served as octet-stream (~400KB, rejected by the image-type guard); the
# /avatars/thumbs/<id> form is a ~15KB image/png. Custom urls pass through.
.sl_avatar_thumb <- function(url) {
  if (grepl("sleepercdn.com/avatars/", url, fixed = TRUE) &&
      !grepl("/thumbs/", url, fixed = TRUE)) {
    sub("/avatars/", "/avatars/thumbs/", url, fixed = TRUE)
  } else url
}

# A cached image file -> a circular rasterGrob (or NULL). Shared by the player
# portrait and manager avatar grobs. `x`/`just` let the caller place the token
# itself (the identity axis right-aligns it against the name column).
.sl_circle_grob <- function(path, size_mm, x = NULL, just = "centre") {
  if (is.null(path)) return(NULL)
  tryCatch({
    # Sniff the magic bytes rather than trust the extension: Sleeper happily
    # serves a PNG from a .jpg url, and readJPEG() then dies on it.
    magic <- readBin(path, "raw", 2L)
    img <- if (identical(as.integer(magic), c(0x89L, 0x50L))) {
      png::readPNG(path)
    } else {
      jpeg::readJPEG(path)
    }
    if (length(dim(img)) == 2L) img <- array(rep(img, 3), c(dim(img), 3))  # greyscale
    n <- min(dim(img)[1:2])                       # centre-crop to a square
    r0 <- floor((dim(img)[1] - n) / 2) + 1
    c0 <- floor((dim(img)[2] - n) / 2) + 1
    img <- img[r0:(r0 + n - 1), c0:(c0 + n - 1), , drop = FALSE]

    # A team logo / avatar png has its own transparency; keep it, or it comes out
    # sitting on a black square.
    own <- if (dim(img)[3] >= 4L) img[, , 4] else matrix(1, n, n)

    # Round it off: alpha 0 outside the inscribed circle.
    ax <- matrix(rep(seq_len(n), each = n), n, n)
    ay <- matrix(rep(seq_len(n), times = n), n, n)
    ctr <- (n + 1) / 2
    inside <- ((ax - ctr)^2 + (ay - ctr)^2) <= (n / 2)^2
    alpha <- own * ifelse(inside, 1, 0)
    rgb <- grDevices::rgb(img[, , 1], img[, , 2], img[, , 3], alpha = alpha)
    args <- list(image = matrix(rgb, n, n), interpolate = TRUE,
                 width = grid::unit(size_mm, "mm"),
                 height = grid::unit(size_mm, "mm"))
    if (!is.null(x)) args <- c(args, list(x = x, just = just))
    do.call(grid::rasterGrob, args)
  }, error = function(e) NULL)
}

#' A player's portrait as a grid raster, ready to draw on a plot
#'
#' Cropped to a square and rounded off, so a portrait sits in the chart as a
#' circular token rather than a photo with a hard rectangular edge.
#'
#' @param player_id Sleeper player id.
#' @param position Player position (`"DEF"` -> team logo).
#' @param size_mm Drawn size. Fixed in mm rather than data units so the portrait
#'   stays a circle instead of being stretched to whatever box it lands in.
#' @param x Optional grid unit for the token's own x position within its
#'   viewport; `just` sets which edge that position refers to.
#' @param just Justification used with `x`.
#' @return A `rasterGrob`, or `NULL` when there is no image.
#' @export
sl_headshot_grob <- function(player_id, position = NULL, size_mm = 6.5,
                             x = NULL, just = "centre") {
  .sl_circle_grob(sl_headshot(player_id, position), size_mm, x, just)
}

#' A manager/team account avatar as a circular grid raster
#'
#' @param url Account avatar url (from the season's `accounts` frame). The
#'   Sleeper `/avatars/<id>` form is fetched via its `/thumbs/` thumbnail.
#' @param size_mm Drawn size (mm).
#' @param x Optional grid unit for the token's own x position within its
#'   viewport; `just` sets which edge that position refers to.
#' @param just Justification used with `x`.
#' @return A `rasterGrob`, or `NULL` when there is no image / no network.
#' @export
sl_avatar_grob <- function(url, size_mm = 6.5, x = NULL, just = "centre") {
  if (is.null(url) || is.na(url) || !nzchar(url)) return(NULL)
  u <- .sl_avatar_thumb(url)
  # Key the cache on the avatar id (the url basename) -- unique and stable, and
  # matches the Python side so both instances share one downloaded set.
  .sl_circle_grob(.sl_fetch_image(u, paste0("av_", basename(u))), size_mm, x, just)
}

# {user_name -> avatar url} from the season's accounts frame (best-effort).
# Prefers the account picture (as the Managers panel does), then a custom team
# picture. Returns a named character vector.
.sl_avatar_map <- function(season) {
  a <- season$accounts
  need <- c("user_name", "avatar_url", "team_avatar_url")
  if (is.null(a) || !nrow(a) || !all(need %in% names(a))) {
    return(stats::setNames(character(0), character(0)))
  }
  url <- ifelse(!is.na(a$avatar_url), a$avatar_url, a$team_avatar_url)
  stats::setNames(url, a$user_name)
}

# Avatar layers for a scatter: each manager's token drawn as the marker at their
# (xcol, ycol) point. `d` needs a user_name column. Caller sets clip = "off".
.sl_point_avatars <- function(season, d, xcol, ycol, size_mm = 5) {
  urls <- .sl_avatar_map(season)
  lays <- list()
  for (i in seq_len(nrow(d))) {
    # `[[` on a named atomic vector ERRORS on a missing name rather than
    # returning NULL, so check membership first: a manager absent from the
    # accounts frame must degrade to their plain dot, not blow the chart up.
    if (!d$user_name[i] %in% names(urls)) next
    u <- urls[[d$user_name[i]]]
    if (is.null(u) || is.na(u) || !nzchar(u)) next
    g <- sl_avatar_grob(u, size_mm)
    if (is.null(g)) next
    lays[[length(lays) + 1L]] <- ggplot2::annotation_custom(
      g, xmin = d[[xcol]][i], xmax = d[[xcol]][i],
      ymin = d[[ycol]][i], ymax = d[[ycol]][i])
  }
  lays
}

#' Forget cached portrait misses (and optionally the downloaded files)
#' @param disk Also delete the cached image files.
#' @return `TRUE`, invisibly.
#' @export
sl_clear_headshots <- function(disk = FALSE) {
  rm(list = ls(envir = .sl_shot_miss), envir = .sl_shot_miss)
  if (disk && dir.exists(.sl_cache_dir())) {
    unlink(list.files(.sl_cache_dir(), full.names = TRUE))
  }
  invisible(TRUE)
}
