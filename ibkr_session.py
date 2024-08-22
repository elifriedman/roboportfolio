import requests
import logging

logger = logging.getLogger(__name__)


class RequestException(Exception):
    pass


class IBKRSession:
    """Serves as the Session for the Interactive Brokers API."""

    def __init__(self, url: str = "https://localhost:5000/v1/api/") -> None:
        """Initializes the `InteractiveBrokersSession` client.

        ### Overview
        ----
        The `InteractiveBrokersSession` object handles all the requests made
        for the different endpoints on the Interactive Brokers API.

        ### Parameters
        ----
        client : object
            The `InteractiveBrokersClient` Python Client.

        ### Usage:
        ----
            >>> ib_session = InteractiveBrokersSession()
        """
        self.resource_url = url
        self.logger = logging.getLogger(f"{logger.name}.session")
        self.logger.setLevel(logging.ERROR)

    def build_url(self, endpoint: str) -> str:
        url = self.resource_url + endpoint
        return url

    def get(self, endpoint: str, params: dict = None, raise_on_error: bool = True) -> dict:
        return self.make_request("get", endpoint=endpoint, params=params, raise_on_error=raise_on_error)

    def post(self, endpoint: str, json_payload: dict = None, raise_on_error: bool = True) -> dict:
        return self.make_request(
            "post",
            endpoint=endpoint,
            json_payload=json_payload,
            raise_on_error=raise_on_error,
        )

    def delete(
        self,
        endpoint: str,
        params: dict = None,
        json_payload: dict = None,
        raise_on_error: bool = True,
    ) -> dict:
        return self.make_request(
            "delete",
            endpoint=endpoint,
            params=params,
            json_payload=json_payload,
            raise_on_error=raise_on_error,
        )

    def make_request(
        self,
        method: str,
        endpoint: str,
        params: dict = None,
        json_payload: dict = None,
        raise_on_error: bool = True,
    ) -> dict:
        """Handles all the requests in the library.

        ### Overview
        ---
        A central function used to handle all the requests made in the library,
        this function handles building the URL, defining Content-Type, passing
        through payloads, and handling any errors that may arise during the
        request.

        ### Parameters
        ----
        method : str
            The Request method, can be one of the following:
            ['get','post','put','delete','patch']

        endpoint : str
            The API URL endpoint, example is 'quotes'

        params : dict (optional, Default={})
            The URL params for the request.

        data : dict (optional, Default={})
        A data payload for a request.

        json_payload : dict (optional, Default={})
            A json data payload for a request

        ### Returns
        ----
        dict:
            A dictionary object containing the
            JSON values.
        """

        url = self.build_url(endpoint=endpoint)
        self.logger.info(msg="------------------------")
        self.logger.info(msg=f"Request Method: {method}")
        self.logger.info(msg="URL: {url}".format(url=url))
        self.logger.info(msg=f"Params: {params}")
        self.logger.info(msg=f"JSON Payload: {json_payload}")
        if method == "post":
            response = requests.post(url=url, params=params, json=json_payload, verify=False)
        elif method == "get":
            response = requests.get(url=url, params=params, json=json_payload, verify=False)
        elif method == "delete":
            response = requests.delete(url=url, params=params, json=json_payload, verify=False)
        self.logger.info(msg=f"Response Status Code: {response.status_code}")
        self.logger.info(msg=f"Response Content: {response.text}")

        if response.ok and len(response.content) > 0:
            return response.json()
        elif not response.ok:
            if len(response.content) == 0:
                response_data = ""
            else:
                try:
                    response_data = response.json()
                except:
                    response_data = response.text

            error_dict = {
                "error_code": response.status_code,
                "error_reason": response.reason,
                "response_url": response.url,
                "response_body": response_data,
                "response_request": {
                    "url": url,
                    "params": params,
                    "json": json_payload,
                    **dict(response.request.headers),
                },
                "response_method": response.request.method,
            }
            if raise_on_error:
                raise RequestException(error_dict)
            return error_dict
