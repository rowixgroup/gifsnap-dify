# GifSnap Dify plugin privacy

Updated October 17, 2026. Publisher: Rowix. Contact: iraklirowix@gmail.com.

## Data sent

When Search GIFs is invoked, the plugin sends the supplied search phrase, page
and result limit in a GET request to `https://gifsnap.com/api/v1/gifs/search`.
The service also receives ordinary connection information, including the Dify
host's IP address and the plugin's versioned User-Agent. Do not include secrets,
private conversations, personal identifiers or sensitive information in a search.
The plugin does not read conversations, user profiles, files, other tools or model
credentials. It processes only the parameters passed to it by the application.

The plugin returns catalog metadata and media URLs to the Dify application.
Dify and the application's configured model may receive this output, and Dify
may retain inputs and outputs in workflow or conversation history according to
that workspace's settings and policies. Consult [Dify's privacy policy](https://dify.ai/privacy)
and your hosting provider. Self-hosted operators control their own retention.

## Storage, logs and external media

The plugin has no persistent storage, cookies, analytics, query logging or
background collection. It does not download media, forward user IP addresses,
follow redirects, send messages or post to another service. Errors omit raw
query strings and upstream response bodies.

GifSnap's service may cache search phrases and results and keep operational
logs. The plugin does not promise that service requests are unlogged or deleted
immediately. See [GifSnap's privacy policy](https://gifsnap.com/privacy) for its
service practices. Search may be fulfilled by GifSnap's catalog or upstream
media services under GifSnap's service policy.

Media URLs can point to external providers/CDNs. The plugin only returns those
URLs. If a downstream app or user opens or embeds them, that client makes a
separate request and the media host receives the network information needed to
serve the file. That host's privacy and content terms then apply.

## Control and contact

Invoking the tool causes the described transmission. Configure it only for
applications where this use is appropriate and disclosed to users. Removing the
plugin stops future requests from it, but does not erase Dify history or service
logs. Contact iraklirowix@gmail.com about GifSnap data questions; contact your
Dify workspace administrator about stored workflow or conversation history.
