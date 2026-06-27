# Functions package for DDBM Fantasy Football script
# FantasyFunctions.R


# Sleeper API Call setup function
# Base URL = "https://api.sleeper.app/v1"
callSleeper <- function(objectId, endpoint = NULL) {
  url <- paste0("https://api.sleeper.app/v1",objectId,endpoint)
  cat("\nSleeper API URL:",url,"\n")
  resp <- request(url) %>%
    req_perform()
  respData <- resp |>
    resp_body_json(simplifyVector = TRUE)

  return(respData)
}
