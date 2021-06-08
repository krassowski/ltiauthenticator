from jupyterhub.app import JupyterHub
from jupyterhub.auth import Authenticator
from jupyterhub.handlers import BaseHandler
from jupyterhub.utils import url_path_join

from tornado.web import HTTPError

from traitlets.config import Dict
from traitlets.config import Unicode

from ltiauthenticator.lti11.handlers import LTI11AuthenticateHandler
from ltiauthenticator.lti11.validator import LTI11LaunchValidator
from ltiauthenticator.utils import convert_request_to_dict
from ltiauthenticator.utils import get_client_protocol


class LTI11Authenticator(Authenticator):
    """
    JupyterHub LTI 1.1 Authenticator which extends the ltiauthenticator.LTIAuthenticator class.
    Messages sent to this authenticator are sent from a tool consumer (TC), such as
    an LMS. JupyterHub, as the authenticator, works as the tool provider (TP), also
    known as the external tool.

    The LTIAuthenticator base class defines the consumers, defined as 1 or (n) consumer key
    and shared secret k/v's to verify requests from their tool consumer.
    """

    auto_login = True
    login_service = "LTI 1.1"

    consumers = Dict(
        {},
        config=True,
        help="""
        A dict of consumer keys mapped to consumer secrets for those keys.
        Allows multiple consumers to securely send users to this JupyterHub
        instance.
        """,
    )

    username_key = Unicode(
        "custom_canvas_user_id",
        allow_none=True,
        config=True,
        help="""
        Key present in LTI 1.1 launch request used to set the user's JupyterHub's username.
        Some common examples include:
          - User's email address: lis_person_contact_email_primary
          - Canvas LMS custom user id: custom_canvas_user_id
        Your LMS (Canvas / Open EdX / Moodle / others) may provide additional keys in the LTI 1.1 launch request that you can use to set the username. In most cases these
        are prefixed with `custom_`. You may also have the option of using variable substitutions to fetch values that aren't provided with your vendor's standard LTI 1.1 launch request.
        Reference the IMS LTI specification on variable substitutions: https://www.imsglobal.org/specs/ltiv1p1p1/implementation-guide#toc-9.
        
        Defaults to custom_canvas_user_id.
        """,
    )

    def get_handlers(self, app: JupyterHub) -> BaseHandler:
        return [("/lti/launch", LTI11AuthenticateHandler)]

    def login_url(self, base_url):
        return url_path_join(base_url, "/lti/launch")

    async def authenticate(  # noqa: C901
        self, handler: BaseHandler, data: dict = None
    ) -> dict:  # noqa: C901
        """
        LTI 1.1 Authenticator. One or more consumer keys/values must be set in the jupyterhub config with the
        LTI11Authenticator.consumers dict.

        Args:
            handler: JupyterHub's Authenticator handler object. For LTI 1.1 requests, the handler is
              an instance of LTIAuthenticateHandler.
            data: optional data object

        Returns:
            Authentication dictionary

        Raises:
            HTTPError if the required values are not in the request
        """
        # log deprecation warning when using the default custom_canvas_user_id setting
        if self.username_key == "custom_canvas_user_id":
            self.log.warning(
                "The default username_key 'custom_canvas_user_id' will be replaced by 'user_id' in a future release."
            )

        validator = LTI11LaunchValidator(self.consumers)

        self.log.debug(
            "Original arguments received in request: %s" % handler.request.arguments
        )

        # extract the request arguments to a dict
        args = convert_request_to_dict(handler.request.arguments)
        self.log.debug("Decoded args from request: %s" % args)

        # get the origin protocol
        protocol = get_client_protocol(handler)
        self.log.debug("Origin protocol is: %s" % protocol)

        # build the full launch url value required for oauth1 signatures
        launch_url = f"{protocol}://{handler.request.host}{handler.request.uri}"
        self.log.debug("Launch url is: %s" % launch_url)

        if validator.validate_launch_request(launch_url, handler.request.headers, args):

            # raise an http error if the username_key is not in the request's arguments.
            if self.username_key not in args.keys():
                raise HTTPError(
                    400,
                    "%s did not match any of the launch request arguments."
                    % self.username_key,
                )

            # get the username_key. if empty, fetch the username from the request's user_id value.
            username = args.get(self.username_key)
            if not username:
                username = args.get("user_id")

            # if username is still empty or none, raise an http error.
            if not username:
                raise HTTPError(
                    400,
                    "The %s value in the launch request is empty or None."
                    % self.username_key,
                )

            # return standard authentication where all launch request arguments are added to the auth_state key
            # except for the oauth_* arguments.
            return {
                "name": username,
                "auth_state": {
                    k: v for k, v in args.items() if not k.startswith("oauth_")
                },
            }
